"""Opt-in process-local Adreno driver loading; never changes the system driver."""
import json
import re
from pathlib import Path
from .benchmark import ROOT, run
from .prepare import sha

SOURCE = ROOT / '.tools/mobile/libadrenotools'
BUILD = ROOT / '.tools/mobile/libadrenotools-build'


def driver_files(directory):
    directory = directory.resolve()
    metadata = json.loads((directory / 'meta.json').read_text())
    name = metadata['libraryName']
    if Path(name).name != name or not (directory / name).is_file():
        raise ValueError('Invalid driver libraryName')
    files = sorted(directory.glob('*.so'))
    return name, files


def link_args():
    return ['-I', SOURCE / 'include', BUILD / 'libadrenotools.a',
            BUILD / 'lib/linkernsbypass/liblinkernsbypass.a', '-ldl']


def activity_source(out):
    """Route every used Vulkan entry through the isolated loader, including WSI."""
    folder = Path(__file__).parent.resolve()
    names = sorted(set(re.findall(r'\b(vk[A-Z]\w*)\s*\(',
                                 '\n'.join((folder / n).read_text() for n in ('runner.cpp', 'activity.cpp')))))
    declarations = '\n'.join(f'static PFN_{n} {n};' for n in names)
    loads = '\n'.join(f'{n}=reinterpret_cast<PFN_{n}>(dlsym(loader,"{n}")); if(!{n}) throw std::runtime_error("Missing {n}");' for n in names)
    wrapper = out / 'custom_activity.cpp'
    wrapper.write_text('''#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_ANDROID_KHR
#include <vulkan/vulkan.h>
#include <adrenotools/driver.h>
#include <dlfcn.h>
''' + declarations + '\n#define ANativeActivity_onCreate original_onCreate\n#include "' + (folder / 'activity.cpp').as_posix() + '''"
#undef ANativeActivity_onCreate
extern "C" __attribute__((visibility("default"))) void ANativeActivity_onCreate(ANativeActivity* a, void* saved, size_t size) {
    try {
        extractBundle(a);
        Dl_info self{};
        if(!dladdr(reinterpret_cast<void*>(&ANativeActivity_onCreate),&self)) throw std::runtime_error("Cannot locate native library directory");
        std::string hookPath=self.dli_fname;
        hookPath=hookPath.substr(0,hookPath.find_last_of('/')+1);
        std::string driverPath=std::string(a->internalDataPath)+"/";
        std::string library; std::ifstream("custom-driver-name.txt")>>library;
        void* loader=adrenotools_open_libvulkan(RTLD_NOW|RTLD_LOCAL,ADRENOTOOLS_DRIVER_CUSTOM,nullptr,hookPath.c_str(),driverPath.c_str(),library.c_str(),nullptr,nullptr);
        if(!loader) throw std::runtime_error("Custom driver loader failed");
''' + loads + '''
        original_onCreate(a,saved,size);
    } catch(const std::exception& e) {
        std::ofstream(std::string(a->internalDataPath)+"/status.txt")<<"ERROR: "<<e.what();
        ANativeActivity_finish(a);
    }
}
''')
    return wrapper


def provenance(directory):
    name, files = driver_files(directory)
    return dict(library=name, files={p.name: sha(p) for p in files},
                metadata=json.loads((directory / 'meta.json').read_text()),
                adrenotools_commit=run(['git', '-C', SOURCE, 'rev-parse', 'HEAD']).strip())
