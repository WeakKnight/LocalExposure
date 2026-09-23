// Headless Android Vulkan execution of the repository's Slang SPIR-V.
// No Python, surface, presentation, readback or host upload in timed regions.
#include <vulkan/vulkan.h>
#include "json.hpp"
#include <algorithm>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
using json = nlohmann::json;
#define VK(call) do { VkResult r=(call); if(r!=VK_SUCCESS) throw std::runtime_error(std::string(#call)+": "+std::to_string(r)); } while(0)
static std::vector<char> read(const std::string& path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("Cannot read "+path);
    auto n=f.tellg(); std::vector<char> b(static_cast<size_t>(n)); f.seekg(0); f.read(b.data(),b.size()); return b;
}
struct Buffer { VkBuffer buffer{}; VkDeviceMemory memory{}; VkDeviceSize size{}; };
struct Image { VkImage image{}; VkDeviceMemory memory{}; std::vector<VkImageView> views;
    uint32_t width{},height{},levels{},bpp{}; bool dump{}; };
struct Pass { VkPipeline pipeline{}; VkPipelineLayout layout{}; VkDescriptorSet set{};
    VkDescriptorSetLayout setLayout{}; Buffer uniform; uint32_t x{},y{}; bool baseline{}; std::string label; };
class Runner {
public:
    VkInstance instance{}; VkPhysicalDevice physical{}; VkDevice device{}; VkQueue queue{};
    VkPhysicalDeviceProperties properties{}; VkPhysicalDeviceMemoryProperties memories{};
    uint32_t family{},validBits{}; VkCommandPool pool{}; VkCommandBuffer cmd{}; VkFence fence{};
    VkSampler sampler{}; VkDescriptorPool descriptors{}; VkQueryPool queries{};
    std::map<std::string,Image> images; std::vector<Pass> passes; std::vector<Buffer> buffers;
    std::vector<VkShaderModule> modules; json manifest; uint32_t productionCount{};
    Runner() {
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.pApplicationName="LocalExposure benchmark"; app.apiVersion=VK_API_VERSION_1_2;
        VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ici.pApplicationInfo=&app;
        VK(vkCreateInstance(&ici,nullptr,&instance));
        uint32_t count=0; VK(vkEnumeratePhysicalDevices(instance,&count,nullptr));
        if(!count) throw std::runtime_error("No Vulkan device");
        std::vector<VkPhysicalDevice> devices(count); VK(vkEnumeratePhysicalDevices(instance,&count,devices.data())); physical=devices[0];
        vkGetPhysicalDeviceProperties(physical,&properties); vkGetPhysicalDeviceMemoryProperties(physical,&memories);
        if(properties.apiVersion < VK_API_VERSION_1_2) throw std::runtime_error("Vulkan 1.2 required");
        vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,nullptr);
        std::vector<VkQueueFamilyProperties> qp(count); vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,qp.data());
        bool found=false;
        for(uint32_t i=0;i<count;i++) if((qp[i].queueFlags&VK_QUEUE_COMPUTE_BIT)&&qp[i].timestampValidBits) {family=i; validBits=qp[i].timestampValidBits; found=true; break;}
        if(!found) throw std::runtime_error("No compute queue with timestamps");
        VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
        VkPhysicalDeviceFeatures2 features{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2}; features.pNext=&f12;
        vkGetPhysicalDeviceFeatures2(physical,&features);
        if(!f12.shaderFloat16 || !features.features.shaderStorageImageReadWithoutFormat || !features.features.shaderStorageImageWriteWithoutFormat)
            throw std::runtime_error("Required float16/storage-image features unavailable");
        // Only enable used features, not every supported optional capability.
        VkPhysicalDeviceVulkan12Features enabled12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES}; enabled12.shaderFloat16=VK_TRUE;
        VkPhysicalDeviceFeatures enabled{}; enabled.shaderStorageImageReadWithoutFormat=VK_TRUE; enabled.shaderStorageImageWriteWithoutFormat=VK_TRUE;
        enabled.shaderStorageImageExtendedFormats=features.features.shaderStorageImageExtendedFormats;
        float priority=1;
        VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qci.queueFamilyIndex=family; qci.queueCount=1; qci.pQueuePriorities=&priority;
        VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dci.pNext=&enabled12; dci.pEnabledFeatures=&enabled; dci.queueCreateInfoCount=1; dci.pQueueCreateInfos=&qci;
        VK(vkCreateDevice(physical,&dci,nullptr,&device)); vkGetDeviceQueue(device,family,0,&queue);
        VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pci.queueFamilyIndex=family; pci.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        VK(vkCreateCommandPool(device,&pci,nullptr,&pool));
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; ai.commandPool=pool; ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ai.commandBufferCount=1;
        VK(vkAllocateCommandBuffers(device,&ai,&cmd));
        VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO}; VK(vkCreateFence(device,&fi,nullptr,&fence));
        VkSamplerCreateInfo si{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO}; si.minFilter=si.magFilter=VK_FILTER_LINEAR;
        si.mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST; si.addressModeU=si.addressModeV=si.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE; si.maxLod=0;
        VK(vkCreateSampler(device,&si,nullptr,&sampler));
        VkDescriptorPoolSize sizes[]={{VK_DESCRIPTOR_TYPE_SAMPLER,256},{VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE,512},{VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,256},{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,128}};
        VkDescriptorPoolCreateInfo di{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO}; di.maxSets=128; di.poolSizeCount=4; di.pPoolSizes=sizes;
        VK(vkCreateDescriptorPool(device,&di,nullptr,&descriptors));
    }
    uint32_t memoryType(uint32_t bits,VkMemoryPropertyFlags flags) {
        for(uint32_t i=0;i<memories.memoryTypeCount;i++) if((bits&(1u<<i)) && (memories.memoryTypes[i].propertyFlags&flags)==flags) return i;
        throw std::runtime_error("No compatible memory type");
    }
    Buffer buffer(VkDeviceSize size,VkBufferUsageFlags usage,const std::vector<char>* bytes=nullptr) {
        Buffer b; b.size=size;
        VkBufferCreateInfo ci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO}; ci.size=size; ci.usage=usage;
        VK(vkCreateBuffer(device,&ci,nullptr,&b.buffer));
        VkMemoryRequirements r; vkGetBufferMemoryRequirements(device,b.buffer,&r);
        VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; ai.allocationSize=r.size;
        ai.memoryTypeIndex=memoryType(r.memoryTypeBits,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        VK(vkAllocateMemory(device,&ai,nullptr,&b.memory)); VK(vkBindBufferMemory(device,b.buffer,b.memory,0));
        if(bytes) {if(bytes->size()!=size) throw std::runtime_error("Buffer size mismatch"); void* p; VK(vkMapMemory(device,b.memory,0,size,0,&p)); memcpy(p,bytes->data(),size); vkUnmapMemory(device,b.memory);}
        buffers.push_back(b); return b;
    }
    void begin() { VK(vkResetCommandBuffer(cmd,0)); VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; VK(vkBeginCommandBuffer(cmd,&bi)); }
    void submit() { VK(vkEndCommandBuffer(cmd)); VK(vkResetFences(device,1,&fence));
        VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO}; si.commandBufferCount=1; si.pCommandBuffers=&cmd;
        VK(vkQueueSubmit(queue,1,&si,fence)); VK(vkWaitForFences(device,1,&fence,VK_TRUE,60000000000ull)); }
    void barrier() {
        VkMemoryBarrier b{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; b.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT; b.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&b,0,nullptr,0,nullptr);
    }
    void load(bool reference=false) {
        std::ifstream f("manifest.json"); f>>manifest;
        if(reference) {
            manifest["resources"].push_back(manifest["reference_resource"]);
            auto& chain=manifest["passes"];
            chain[chain.size()-2]=manifest["reference_pass"];
        }
        begin();
        for(const auto& r:manifest["resources"]) {
            Image im; im.width=r["width"]; im.height=r["height"]; im.levels=r["levels"]; im.bpp=r["bpp"]; im.dump=r["dump"];
            bool one=r["one_d"]; auto format=VkFormat(r["format"].get<int>());
            VkFormatProperties fp; vkGetPhysicalDeviceFormatProperties(physical,format,&fp);
            const VkFormatFeatureFlags needed=VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT|VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT;
            if((fp.optimalTilingFeatures&needed)!=needed) throw std::runtime_error("Unsupported format "+r["format_name"].get<std::string>());
            VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO}; ci.imageType=one?VK_IMAGE_TYPE_1D:VK_IMAGE_TYPE_2D; ci.format=format;
            ci.extent={im.width,im.height,1}; ci.mipLevels=im.levels; ci.arrayLayers=1; ci.samples=VK_SAMPLE_COUNT_1_BIT; ci.tiling=VK_IMAGE_TILING_OPTIMAL;
            ci.usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_STORAGE_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
            VK(vkCreateImage(device,&ci,nullptr,&im.image));
            VkMemoryRequirements mr; vkGetImageMemoryRequirements(device,im.image,&mr);
            VkMemoryAllocateInfo ma{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; ma.allocationSize=mr.size; ma.memoryTypeIndex=memoryType(mr.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
            VK(vkAllocateMemory(device,&ma,nullptr,&im.memory)); VK(vkBindImageMemory(device,im.image,im.memory,0));
            for(uint32_t m=0;m<im.levels;m++) {
                VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO}; vi.image=im.image; vi.viewType=one?VK_IMAGE_VIEW_TYPE_1D:VK_IMAGE_VIEW_TYPE_2D; vi.format=format;
                vi.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,m,1,0,1}; VkImageView view; VK(vkCreateImageView(device,&vi,nullptr,&view)); im.views.push_back(view);
            }
            VkImageMemoryBarrier ib{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER}; ib.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED; ib.newLayout=VK_IMAGE_LAYOUT_GENERAL;
            ib.srcQueueFamilyIndex=ib.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED; ib.image=im.image; ib.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,im.levels,0,1}; ib.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
            vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&ib);
            VkClearColorValue zero{}; vkCmdClearColorImage(cmd,im.image,VK_IMAGE_LAYOUT_GENERAL,&zero,1,&ib.subresourceRange);
            if(r.contains("file")) {
                // Order clear before upload, including their overlapping mip 0 writes.
                VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; mb.srcAccessMask=mb.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
                vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,1,&mb,0,nullptr,0,nullptr);
                auto bytes=read(r["file"]); auto staging=buffer(bytes.size(),VK_BUFFER_USAGE_TRANSFER_SRC_BIT,&bytes);
                if(bytes.size()!=size_t(im.width)*im.height*im.bpp) throw std::runtime_error("Image payload size mismatch");
                VkBufferImageCopy region{}; region.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}; region.imageExtent={im.width,im.height,1};
                vkCmdCopyBufferToImage(cmd,staging.buffer,im.image,VK_IMAGE_LAYOUT_GENERAL,1,&region);
            }
            images.emplace(r["name"].get<std::string>(),im);
        }
        VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; mb.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; mb.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&mb,0,nullptr,0,nullptr); submit();
        for(const auto& p:manifest["passes"]) makePass(p);
        productionCount=uint32_t(passes.size()-1);
        VkQueryPoolCreateInfo qi{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO}; qi.queryType=VK_QUERY_TYPE_TIMESTAMP; qi.queryCount=2*productionCount+2;
        VK(vkCreateQueryPool(device,&qi,nullptr,&queries));
    }
    void makePass(const json& p) {
        Pass pass; pass.label=p["label"]; pass.x=(p["width"].get<uint32_t>()+7)/8; pass.y=(p["height"].get<uint32_t>()+7)/8; pass.baseline=p["baseline"];
        // Slang's implicit global constant buffer is descriptor 0 for these modules.
        std::vector<VkDescriptorSetLayoutBinding> bindings={{0,VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr}};
        for(auto& d:p["descriptors"]) bindings.push_back({d["binding"],VkDescriptorType(d["type"].get<int>()),1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr});
        VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO}; li.bindingCount=bindings.size(); li.pBindings=bindings.data();
        VK(vkCreateDescriptorSetLayout(device,&li,nullptr,&pass.setLayout));
        VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; pi.setLayoutCount=1; pi.pSetLayouts=&pass.setLayout;
        VK(vkCreatePipelineLayout(device,&pi,nullptr,&pass.layout));
        auto bytes=read(p["entry"].get<std::string>()+".spv"); std::vector<uint32_t> words(bytes.size()/4); memcpy(words.data(),bytes.data(),bytes.size());
        VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; mi.codeSize=bytes.size(); mi.pCode=words.data(); VkShaderModule module;
        VK(vkCreateShaderModule(device,&mi,nullptr,&module)); modules.push_back(module);
        auto entry=p["entry"].get<std::string>(); VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO}; ci.layout=pass.layout;
        ci.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}; ci.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT; ci.stage.module=module; ci.stage.pName=entry.c_str();
        VK(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&ci,nullptr,&pass.pipeline));
        VkDescriptorSetAllocateInfo ai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO}; ai.descriptorPool=descriptors; ai.descriptorSetCount=1; ai.pSetLayouts=&pass.setLayout;
        VK(vkAllocateDescriptorSets(device,&ai,&pass.set));
        auto constants=read(p["uniform"]); pass.uniform=buffer(constants.size(),VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,&constants);
        VkDescriptorBufferInfo bi{pass.uniform.buffer,0,pass.uniform.size}; VkWriteDescriptorSet write{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET}; write.dstSet=pass.set; write.descriptorCount=1;
        write.descriptorType=VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER; write.pBufferInfo=&bi; vkUpdateDescriptorSets(device,1,&write,0,nullptr);
        for(auto& d:p["descriptors"]) {
            VkDescriptorImageInfo ii{}; auto type=VkDescriptorType(d["type"].get<int>());
            if(type==VK_DESCRIPTOR_TYPE_SAMPLER) ii.sampler=sampler;
            else {ii.imageView=images.at(d["resource"].get<std::string>()).views.at(d["mip"].get<size_t>()); ii.imageLayout=VK_IMAGE_LAYOUT_GENERAL;}
            VkWriteDescriptorSet w{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET}; w.dstSet=pass.set; w.dstBinding=d["binding"]; w.descriptorCount=1; w.descriptorType=type; w.pImageInfo=&ii;
            vkUpdateDescriptorSets(device,1,&w,0,nullptr);
        }
        passes.push_back(pass);
    }
    void dispatch(const Pass& p) {
        vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.pipeline);
        vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.layout,0,1,&p.set,0,nullptr);
        vkCmdDispatch(cmd,p.x,p.y,1);
    }
    // Separate whole-chain and diagnostic modes: per-pass timestamps serialize
    // stages more than the ordinary chain and must not supply headline totals.
    void record(bool baseline,bool diagnostic) {
        begin(); vkCmdResetQueryPool(cmd,queries,0,2*productionCount+2); barrier();
        vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queries,0);
        uint32_t index=0;
        for(const auto& p:passes) if(p.baseline==baseline) {
            if(diagnostic) vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queries,2+2*index);
            dispatch(p); barrier();
            if(diagnostic) vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queries,3+2*index);
            index++;
        }
        vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queries,1);
        VK(vkEndCommandBuffer(cmd));
    }
    std::vector<double> execute(uint32_t queryCount) {
        VK(vkResetFences(device,1,&fence)); VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO}; si.commandBufferCount=1; si.pCommandBuffers=&cmd;
        VK(vkQueueSubmit(queue,1,&si,fence)); VK(vkWaitForFences(device,1,&fence,VK_TRUE,60000000000ull));
        std::vector<uint64_t> ticks(queryCount); VK(vkGetQueryPoolResults(device,queries,0,queryCount,ticks.size()*8,ticks.data(),8,VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WAIT_BIT));
        const uint64_t mask=validBits==64?~uint64_t(0):(uint64_t(1)<<validBits)-1;
        std::vector<double> ms; for(size_t i=0;i<ticks.size();i+=2) ms.push_back(double((ticks[i+1]-ticks[i])&mask)*properties.limits.timestampPeriod/1e6); return ms;
    }
    json measure(int warmup,int frames,int rounds,int intervalMs) {
        json result; result["device"]=properties.deviceName; result["vendor_id"]=properties.vendorID;
        result["device_id"]=properties.deviceID; result["driver_version"]=properties.driverVersion;
        result["api_version"]=properties.apiVersion; result["timestamp_period_ns"]=properties.limits.timestampPeriod;
        result["timestamp_valid_bits"]=validBits; result["queue_family"]=family;
        result["warmup_frames_per_block"]=warmup; result["frames_per_block"]=frames; result["rounds"]=rounds; result["interval_ms"]=intervalMs;
        result["passes"]=json::array(); for(const auto& p:passes) if(!p.baseline) result["passes"].push_back(p.label);
        result["blocks"]=json::array();
        // AB/BA alternation reduces ordering bias; it cannot lock DVFS or temperature.
        for(int round=0;round<rounds;round++) for(int phase=0;phase<2;phase++) {
            bool baseline=(round+phase)%2==1; record(baseline,false);
            json samples=json::array();
            for(int i=-warmup;i<frames;i++) {
                auto start=std::chrono::steady_clock::now(); auto v=execute(2);
                if(i>=0) samples.push_back(v[0]);
                if(intervalMs>0) std::this_thread::sleep_until(start+std::chrono::milliseconds(intervalMs));
            }
            result["blocks"].push_back({{"round",round},{"kind",baseline?"baseline":"fusion"},{"gpu_ms",samples}});
            std::cerr<<"Round "<<round<<" "<<(baseline?"baseline":"fusion")<<" complete\n";
        }
        record(false,true); for(int i=0;i<warmup;i++) execute(2+2*productionCount);
        result["diagnostic_ms"]=json::array();
        for(int i=0;i<frames;i++) {result["diagnostic_ms"].push_back(execute(2+2*productionCount)); if(intervalMs) std::this_thread::sleep_for(std::chrono::milliseconds(intervalMs));}
        return result;
    }
    void dump() {
        // Last execution is Fusion; reference readback happens after all timing.
        begin(); VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; mb.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT; mb.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,1,&mb,0,nullptr,0,nullptr);
        std::vector<std::pair<std::string,Buffer>> dumps;
        for(auto& [name,im]:images) if(im.dump) {
            auto b=buffer(VkDeviceSize(im.width)*im.height*im.bpp,VK_BUFFER_USAGE_TRANSFER_DST_BIT);
            VkBufferImageCopy region{}; region.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}; region.imageExtent={im.width,im.height,1};
            vkCmdCopyImageToBuffer(cmd,im.image,VK_IMAGE_LAYOUT_GENERAL,b.buffer,1,&region); dumps.emplace_back(name,b);
        }
        mb.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; mb.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&mb,0,nullptr,0,nullptr); submit();
        for(auto& [name,b]:dumps) {void* p; VK(vkMapMemory(device,b.memory,0,b.size,0,&p)); std::ofstream f(name+".device.bin",std::ios::binary); f.write(static_cast<char*>(p),b.size); vkUnmapMemory(device,b.memory);}
    }
    void verify() {
        begin(); barrier();
        for(const auto& p:passes) if(!p.baseline) {dispatch(p); barrier();}
        submit(); dump();
    }
    ~Runner() {
        if(!device) return; vkDeviceWaitIdle(device);
        for(auto& p:passes) {vkDestroyPipeline(device,p.pipeline,nullptr); vkDestroyPipelineLayout(device,p.layout,nullptr); vkDestroyDescriptorSetLayout(device,p.setLayout,nullptr);}
        for(auto m:modules) vkDestroyShaderModule(device,m,nullptr);
        for(auto& [name,im]:images) {for(auto v:im.views) vkDestroyImageView(device,v,nullptr); vkDestroyImage(device,im.image,nullptr); vkFreeMemory(device,im.memory,nullptr);}
        for(auto& b:buffers) {vkDestroyBuffer(device,b.buffer,nullptr); vkFreeMemory(device,b.memory,nullptr);}
        vkDestroyQueryPool(device,queries,nullptr); vkDestroyDescriptorPool(device,descriptors,nullptr); vkDestroySampler(device,sampler,nullptr);
        vkDestroyFence(device,fence,nullptr); vkDestroyCommandPool(device,pool,nullptr); vkDestroyDevice(device,nullptr); vkDestroyInstance(instance,nullptr);
    }
};
int main(int argc,char** argv) {
    try {
        int warmup=argc>1?std::stoi(argv[1]):60, frames=argc>2?std::stoi(argv[2]):120;
        int rounds=argc>3?std::stoi(argv[3]):3, interval=argc>4?std::stoi(argv[4]):16;
        if(warmup<0||frames<1||rounds<1||interval<0) throw std::runtime_error("Invalid run counts");
        bool reference=argc>5 && std::string(argv[5])=="verify";
        Runner r; std::cerr<<r.properties.deviceName<<"\n"; r.load(reference);
        if(reference) {r.verify(); return 0;}
        auto result=r.measure(warmup,frames,rounds,interval); r.dump();
        std::ofstream("timings.json")<<result.dump(2)<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n"; return 1;}
}
