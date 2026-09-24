// Capability gate for the optional Qualcomm tile-memory experiment.
#include <vulkan/vulkan.h>
#include "json.hpp"
#include <iostream>
#include <vector>
#include <stdexcept>
#include <cstring>
#ifdef LOCAL_EXPOSURE_CUSTOM_DRIVER
#include <adrenotools/driver.h>
#include <dlfcn.h>
#endif
using nlohmann::json;
static void check(VkResult r) { if(r!=VK_SUCCESS) throw std::runtime_error("Vulkan result "+std::to_string(r)); }
int main(int argc, char** argv) {
    try {
#ifdef LOCAL_EXPOSURE_CUSTOM_DRIVER
        if(argc<6) throw std::runtime_error("Expected API, surface mode, hook directory, driver directory, driver library");
        void* loader=adrenotools_open_libvulkan(RTLD_NOW|RTLD_LOCAL,ADRENOTOOLS_DRIVER_CUSTOM,
            nullptr,argv[3],argv[4],argv[5],nullptr,nullptr);
        if(!loader) throw std::runtime_error("Custom Vulkan loader failed");
#define LOAD_VK(name) auto name=reinterpret_cast<PFN_##name>(dlsym(loader,#name)); if(!name) throw std::runtime_error("Missing " #name)
        LOAD_VK(vkGetInstanceProcAddr);
        LOAD_VK(vkCreateInstance);
        LOAD_VK(vkEnumeratePhysicalDevices);
        LOAD_VK(vkGetPhysicalDeviceProperties);
        LOAD_VK(vkEnumerateDeviceExtensionProperties);
        LOAD_VK(vkGetPhysicalDeviceMemoryProperties);
        LOAD_VK(vkGetPhysicalDeviceFeatures2);
        LOAD_VK(vkGetPhysicalDeviceProperties2);
        LOAD_VK(vkDestroyInstance);
#undef LOAD_VK
#endif
        uint32_t loaderVersion=VK_API_VERSION_1_0;
        auto enumerateVersion=reinterpret_cast<PFN_vkEnumerateInstanceVersion>(vkGetInstanceProcAddr(VK_NULL_HANDLE,"vkEnumerateInstanceVersion"));
        if(enumerateVersion) check(enumerateVersion(&loaderVersion));
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
        app.apiVersion=(argc>1 && !strcmp(argv[1],"max"))?loaderVersion:VK_API_VERSION_1_2;
        VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ci.pApplicationInfo=&app;
        const char* surfaceExtensions[]={"VK_KHR_surface","VK_KHR_android_surface"};
        bool surface=argc>2 && !strcmp(argv[2],"surface");
        if(surface) {ci.enabledExtensionCount=2;ci.ppEnabledExtensionNames=surfaceExtensions;}
        VkInstance instance; check(vkCreateInstance(&ci,nullptr,&instance));
        uint32_t n=0; check(vkEnumeratePhysicalDevices(instance,&n,nullptr));
        std::vector<VkPhysicalDevice> devices(n); check(vkEnumeratePhysicalDevices(instance,&n,devices.data()));
        json result=json::array();
        for(auto device:devices) {
            VkPhysicalDeviceProperties props; vkGetPhysicalDeviceProperties(device,&props);
            check(vkEnumerateDeviceExtensionProperties(device,nullptr,&n,nullptr));
            std::vector<VkExtensionProperties> extensions(n);
            check(vkEnumerateDeviceExtensionProperties(device,nullptr,&n,extensions.data()));
            bool supported=false; json names=json::array();
            for(auto& e:extensions) {
                names.push_back(e.extensionName);
                supported |= !strcmp(e.extensionName,VK_QCOM_TILE_MEMORY_HEAP_EXTENSION_NAME);
            }
            VkPhysicalDeviceMemoryProperties memory; vkGetPhysicalDeviceMemoryProperties(device,&memory);
            json heaps=json::array(); bool tileHeap=false;
            for(uint32_t i=0;i<memory.memoryHeapCount;i++) {
                bool tile=(memory.memoryHeaps[i].flags&VK_MEMORY_HEAP_TILE_MEMORY_BIT_QCOM)!=0;
                tileHeap |= tile;
                heaps.push_back({{"index",i},{"bytes",memory.memoryHeaps[i].size},{"flags",memory.memoryHeaps[i].flags},{"tile",tile}});
            }
            json item={{"device",props.deviceName},{"api_version",props.apiVersion},{"driver_version",props.driverVersion},
                {"tile_memory_extension",supported},{"heaps",heaps},{"extensions",names},
                {"instance_api_version",app.apiVersion},{"loader_api_version",loaderVersion},{"surface_extensions_enabled",surface},
                {"header_version",VK_HEADER_VERSION}};
            if(props.apiVersion>=VK_API_VERSION_1_2) {
                VkPhysicalDeviceDriverProperties driver{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
                VkPhysicalDeviceProperties2 p{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2}; p.pNext=&driver;
                vkGetPhysicalDeviceProperties2(device,&p);
                item["driver_name"]=driver.driverName; item["driver_info"]=driver.driverInfo;
            }
            bool feature=false;
            if(supported) {
                VkPhysicalDeviceTileMemoryHeapFeaturesQCOM tile{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TILE_MEMORY_HEAP_FEATURES_QCOM};
                VkPhysicalDeviceFeatures2 f{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2}; f.pNext=&tile;
                vkGetPhysicalDeviceFeatures2(device,&f); feature=tile.tileMemoryHeap;
                VkPhysicalDeviceTileMemoryHeapPropertiesQCOM tp{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TILE_MEMORY_HEAP_PROPERTIES_QCOM};
                VkPhysicalDeviceProperties2 p{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2}; p.pNext=&tp;
                vkGetPhysicalDeviceProperties2(device,&p);
                item["tile_memory_feature"]=feature; item["queue_submit_boundary"]=bool(tp.queueSubmitBoundary);
            }
            item["eligible"]=supported&&feature&&tileHeap;
            result.push_back(item);
        }
        vkDestroyInstance(instance,nullptr);
        std::cout<<result.dump(2)<<std::endl;
    } catch(const std::exception& e) { std::cerr<<e.what()<<std::endl; return 1; }
}
