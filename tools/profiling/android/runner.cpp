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
#define VK(call) do { VkResult vkResultChecked_=(call); if(vkResultChecked_!=VK_SUCCESS) throw std::runtime_error(std::string(#call)+": "+std::to_string(vkResultChecked_)); } while(0)
static std::vector<char> read(const std::string& path) {
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("Cannot read "+path);
    auto n=f.tellg(); std::vector<char> b(static_cast<size_t>(n)); f.seekg(0); f.read(b.data(),b.size()); return b;
}
struct Buffer { VkBuffer buffer{}; VkDeviceMemory memory{}; VkDeviceSize size{}; };
struct Image { VkImage image{}; VkDeviceMemory memory{}; std::vector<VkImageView> views;
    uint32_t width{},height{},levels{},bpp{}; bool dump{}; VkImageLayout layout=VK_IMAGE_LAYOUT_GENERAL; };
struct Pass { VkPipeline pipeline{}; VkPipelineLayout layout{}; VkDescriptorSet set{};
    VkDescriptorSetLayout setLayout{}; Buffer uniform; uint32_t x{},y{},width{},height{}; bool baseline{},graphics{};
    VkRenderPass renderPass{}; VkFramebuffer framebuffer{}; std::string label; };
class Runner {
public:
    VkInstance instance{}; VkPhysicalDevice physical{}; VkDevice device{}; VkQueue queue{},graphicsQueue{};
    VkPhysicalDeviceProperties properties{}; VkPhysicalDeviceMemoryProperties memories{};
    uint32_t family{},graphicsFamily{},validBits{}; VkQueueFlags queueFlags{}; VkCommandPool pool{},graphicsPool{}; VkCommandBuffer cmd{}; VkFence fence{};
    VkSampler sampler{}; VkDescriptorPool descriptors{}; VkQueryPool queries{};
    std::map<std::string,Image> images; std::vector<Pass> passes; std::vector<Buffer> buffers;
    std::vector<VkShaderModule> modules; json manifest; uint32_t productionCount{};
    double lastSubmitQueryMs{};
    bool hasGraphics=false;
    std::string calibrationExtension;
    Runner(bool calibrate=false,bool windowed=false,bool separateQueue=false,bool dedicatedCompute=false) {
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.pApplicationName="LocalExposure benchmark"; app.apiVersion=VK_API_VERSION_1_2;
        VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ici.pApplicationInfo=&app;
        const char* surfaceExtensions[]={"VK_KHR_surface","VK_KHR_android_surface"};
        if(windowed) {ici.enabledExtensionCount=2;ici.ppEnabledExtensionNames=surfaceExtensions;}
        VK(vkCreateInstance(&ici,nullptr,&instance));
        uint32_t count=0; VK(vkEnumeratePhysicalDevices(instance,&count,nullptr));
        if(!count) throw std::runtime_error("No Vulkan device");
        std::vector<VkPhysicalDevice> devices(count); VK(vkEnumeratePhysicalDevices(instance,&count,devices.data())); physical=devices[0];
        vkGetPhysicalDeviceProperties(physical,&properties); vkGetPhysicalDeviceMemoryProperties(physical,&memories);
        if(properties.apiVersion < VK_API_VERSION_1_2) throw std::runtime_error("Vulkan 1.2 required");
        vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,nullptr);
        std::vector<VkQueueFamilyProperties> qp(count); vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,qp.data());
        bool found=false;
        for(uint32_t i=0;i<count;i++) if((qp[i].queueFlags&VK_QUEUE_COMPUTE_BIT)&&qp[i].timestampValidBits) {family=i; queueFlags=qp[i].queueFlags; validBits=qp[i].timestampValidBits; found=true; break;}
        if(!found) throw std::runtime_error("No compute queue with timestamps");
        graphicsFamily=family;
        if(dedicatedCompute){
            bool dedicatedFound=false;
            for(uint32_t i=0;i<count;i++)if((qp[i].queueFlags&VK_QUEUE_COMPUTE_BIT)&&!(qp[i].queueFlags&VK_QUEUE_GRAPHICS_BIT)&&qp[i].timestampValidBits){family=i;queueFlags=qp[i].queueFlags;validBits=qp[i].timestampValidBits;dedicatedFound=true;break;}
            if(!dedicatedFound)throw std::runtime_error("Dedicated compute queue unavailable");
        }
        VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
        VkPhysicalDeviceFeatures2 features{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2}; features.pNext=&f12;
        vkGetPhysicalDeviceFeatures2(physical,&features);
        if(!f12.shaderFloat16 || !features.features.shaderStorageImageReadWithoutFormat || !features.features.shaderStorageImageWriteWithoutFormat)
            throw std::runtime_error("Required float16/storage-image features unavailable");
        // Only enable used features, not every supported optional capability.
        VkPhysicalDeviceVulkan12Features enabled12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES}; enabled12.shaderFloat16=VK_TRUE;
        VkPhysicalDeviceFeatures enabled{}; enabled.shaderStorageImageReadWithoutFormat=VK_TRUE; enabled.shaderStorageImageWriteWithoutFormat=VK_TRUE;
        enabled.shaderStorageImageExtendedFormats=features.features.shaderStorageImageExtendedFormats;
        float priorities[]={1,1};
        if(separateQueue && qp[family].queueCount<2)throw std::runtime_error("Two same-family queues unavailable");
        VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qci.queueFamilyIndex=family; qci.queueCount=separateQueue?2:1; qci.pQueuePriorities=priorities;
        VkDeviceQueueCreateInfo queues[2]={qci,qci};queues[1].queueFamilyIndex=graphicsFamily;queues[1].queueCount=1;
        VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dci.pNext=&enabled12; dci.pEnabledFeatures=&enabled; dci.queueCreateInfoCount=dedicatedCompute?2:1; dci.pQueueCreateInfos=queues;
        std::vector<const char*> deviceExtensions;
        if(windowed) deviceExtensions.push_back("VK_KHR_swapchain");
        if(calibrate) {
            uint32_t extensionCount=0; VK(vkEnumerateDeviceExtensionProperties(physical,nullptr,&extensionCount,nullptr));
            std::vector<VkExtensionProperties> extensions(extensionCount);
            VK(vkEnumerateDeviceExtensionProperties(physical,nullptr,&extensionCount,extensions.data()));
            for(const auto& e:extensions) if(std::string(e.extensionName)=="VK_EXT_calibrated_timestamps") calibrationExtension=e.extensionName;
            if(!calibrationExtension.empty()) deviceExtensions.push_back(calibrationExtension.c_str());
        }
        dci.enabledExtensionCount=deviceExtensions.size();dci.ppEnabledExtensionNames=deviceExtensions.data();
        VK(vkCreateDevice(physical,&dci,nullptr,&device)); vkGetDeviceQueue(device,family,0,&queue);
        vkGetDeviceQueue(device,graphicsFamily,separateQueue?1:0,&graphicsQueue);
        VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pci.queueFamilyIndex=family; pci.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        VK(vkCreateCommandPool(device,&pci,nullptr,&pool));graphicsPool=pool;
        if(graphicsFamily!=family){pci.queueFamilyIndex=graphicsFamily;VK(vkCreateCommandPool(device,&pci,nullptr,&graphicsPool));}
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
        uint32_t sharingFamilies[]={family,graphicsFamily};
        if(family!=graphicsFamily){ci.sharingMode=VK_SHARING_MODE_CONCURRENT;ci.queueFamilyIndexCount=2;ci.pQueueFamilyIndices=sharingFamilies;}
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
    void barrier(bool fromGraphics=false,bool toGraphics=false) {
        VkMemoryBarrier b{VK_STRUCTURE_TYPE_MEMORY_BARRIER};
        b.srcAccessMask=fromGraphics?VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT:VK_ACCESS_SHADER_WRITE_BIT;
        b.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|(toGraphics?VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT:VK_ACCESS_SHADER_WRITE_BIT);
        VkPipelineStageFlags from=fromGraphics?VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT:VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT;
        VkPipelineStageFlags to=toGraphics?(VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT|VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT):VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT;
        vkCmdPipelineBarrier(cmd,from,to,0,1,&b,0,nullptr,0,nullptr);
    }
    void load(bool reference=false) {
        std::ifstream f("manifest.json"); f>>manifest;
        if(reference) {
            if(manifest.contains("unfused_passes")) {
                manifest["passes"]=manifest["unfused_passes"];
                manifest["resources"]=manifest["unfused_resources"];
            }
            manifest["resources"].push_back(manifest["reference_resource"]);
            if(manifest.contains("reference_resources")) for(auto& extra:manifest["reference_resources"]) manifest["resources"].push_back(extra);
            auto& chain=manifest["passes"];
            chain[chain.size()-2]=manifest["reference_pass"];
            if(manifest.contains("reference_resolve")) chain.insert(chain.end()-1,manifest["reference_resolve"]);
        }
        for(auto& p:manifest["passes"]) hasGraphics|=p.contains("attachment");
        if(hasGraphics && graphicsFamily==family && !(queueFlags&VK_QUEUE_GRAPHICS_BIT)) throw std::runtime_error("Selected compute queue does not support graphics");
        begin();
        for(const auto& r:manifest["resources"]) {
            Image im; im.width=r["width"]; im.height=r["height"]; im.levels=r["levels"]; im.bpp=r["bpp"]; im.dump=r["dump"];
            bool one=r["one_d"]; auto format=VkFormat(r["format"].get<int>());
            VkFormatProperties fp; vkGetPhysicalDeviceFormatProperties(physical,VkFormat(r.value("storage_view_format",int(format))),&fp);
            bool attachment=r.value("attachment",false),sampledOnly=r.value("sampled_only",false);
            const VkFormatFeatureFlags needed=attachment?VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT:
                VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT|(sampledOnly?0:VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT);
            if((fp.optimalTilingFeatures&needed)!=needed) throw std::runtime_error("Unsupported format "+r["format_name"].get<std::string>());
            VkImageCreateInfo ci{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO}; ci.imageType=one?VK_IMAGE_TYPE_1D:VK_IMAGE_TYPE_2D; ci.format=format;
            if(r.contains("storage_view_format")) ci.flags=VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT|VK_IMAGE_CREATE_EXTENDED_USAGE_BIT;
            ci.extent={im.width,im.height,1}; ci.mipLevels=im.levels; ci.arrayLayers=1; ci.samples=VK_SAMPLE_COUNT_1_BIT; ci.tiling=VK_IMAGE_TILING_OPTIMAL;
            ci.usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_STORAGE_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
            if(sampledOnly) ci.usage&=~VK_IMAGE_USAGE_STORAGE_BIT;
            if(attachment) ci.usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
            if(r.value("sampled_attachment",false))ci.usage|=VK_IMAGE_USAGE_SAMPLED_BIT;
            uint32_t sharingFamilies[]={family,graphicsFamily};
            if(family!=graphicsFamily){ci.sharingMode=VK_SHARING_MODE_CONCURRENT;ci.queueFamilyIndexCount=2;ci.pQueueFamilyIndices=sharingFamilies;}
            VK(vkCreateImage(device,&ci,nullptr,&im.image));
            VkMemoryRequirements mr; vkGetImageMemoryRequirements(device,im.image,&mr);
            VkMemoryAllocateInfo ma{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; ma.allocationSize=mr.size; ma.memoryTypeIndex=memoryType(mr.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
            VK(vkAllocateMemory(device,&ma,nullptr,&im.memory)); VK(vkBindImageMemory(device,im.image,im.memory,0));
            for(uint32_t m=0;m<im.levels;m++) {
                VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO}; vi.image=im.image; vi.viewType=one?VK_IMAGE_VIEW_TYPE_1D:VK_IMAGE_VIEW_TYPE_2D; vi.format=VkFormat(r.value("storage_view_format",int(format)));
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
            if(sampledOnly) {
                ib.oldLayout=VK_IMAGE_LAYOUT_GENERAL;ib.newLayout=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
                ib.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;ib.dstAccessMask=VK_ACCESS_SHADER_READ_BIT;
                vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT|(family==graphicsFamily?VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT:0),0,0,nullptr,0,nullptr,1,&ib);
                im.layout=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            }
            images.emplace(r["name"].get<std::string>(),im);
        }
        VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; mb.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; mb.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT;
        VkPipelineStageFlags readers=VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT;
        if(hasGraphics && family==graphicsFamily) readers|=VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT|VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,readers,0,1,&mb,0,nullptr,0,nullptr); submit();
        for(const auto& p:manifest["passes"]) makePass(p);
        productionCount=uint32_t(passes.size()-1);
        VkQueryPoolCreateInfo qi{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO}; qi.queryType=VK_QUERY_TYPE_TIMESTAMP; qi.queryCount=2*productionCount+2;
        VK(vkCreateQueryPool(device,&qi,nullptr,&queries));
    }
    void makePass(const json& p) {
        auto group=p.value("group_size",std::vector<uint32_t>{8,8,1});
        if(group.size()!=3 || !group[0] || !group[1] || group[2]!=1) throw std::runtime_error("Invalid compute group size");
        Pass pass; pass.label=p["label"]; pass.width=p["width"]; pass.height=p["height"]; pass.x=(pass.width+group[0]-1)/group[0]; pass.y=(pass.height+group[1]-1)/group[1]; pass.baseline=p["baseline"];
        if(p.contains("dispatch_groups")){pass.x=p["dispatch_groups"][0];pass.y=p["dispatch_groups"][1];}
        pass.graphics=p.contains("attachment"); hasGraphics|=pass.graphics;
        VkShaderStageFlags stageFlags=pass.graphics?VK_SHADER_STAGE_FRAGMENT_BIT:VK_SHADER_STAGE_COMPUTE_BIT;
        // Slang's implicit global constant buffer is descriptor 0 for these modules.
        std::vector<VkDescriptorSetLayoutBinding> bindings={{0,VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1,stageFlags,nullptr}};
        for(auto& d:p["descriptors"]) bindings.push_back({d["binding"],VkDescriptorType(d["type"].get<int>()),1,stageFlags,nullptr});
        VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO}; li.bindingCount=bindings.size(); li.pBindings=bindings.data();
        VK(vkCreateDescriptorSetLayout(device,&li,nullptr,&pass.setLayout));
        VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; pi.setLayoutCount=1; pi.pSetLayouts=&pass.setLayout;
        VK(vkCreatePipelineLayout(device,&pi,nullptr,&pass.layout));
        auto bytes=read(p["entry"].get<std::string>()+".spv"); std::vector<uint32_t> words(bytes.size()/4); memcpy(words.data(),bytes.data(),bytes.size());
        VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; mi.codeSize=bytes.size(); mi.pCode=words.data(); VkShaderModule module;
        VK(vkCreateShaderModule(device,&mi,nullptr,&module)); modules.push_back(module);
        auto entry=p["entry"].get<std::string>(); VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO}; ci.layout=pass.layout;
        ci.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}; ci.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT; ci.stage.module=module; ci.stage.pName=entry.c_str();
        if(pass.graphics) makeGraphics(pass,p,module,entry);
        else VK(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&ci,nullptr,&pass.pipeline));
        VkDescriptorSetAllocateInfo ai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO}; ai.descriptorPool=descriptors; ai.descriptorSetCount=1; ai.pSetLayouts=&pass.setLayout;
        VK(vkAllocateDescriptorSets(device,&ai,&pass.set));
        auto constants=read(p["uniform"]); pass.uniform=buffer(constants.size(),VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,&constants);
        VkDescriptorBufferInfo bi{pass.uniform.buffer,0,pass.uniform.size}; VkWriteDescriptorSet write{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET}; write.dstSet=pass.set; write.descriptorCount=1;
        write.descriptorType=VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER; write.pBufferInfo=&bi; vkUpdateDescriptorSets(device,1,&write,0,nullptr);
        for(auto& d:p["descriptors"]) {
            VkDescriptorImageInfo ii{}; auto type=VkDescriptorType(d["type"].get<int>());
            if(type==VK_DESCRIPTOR_TYPE_SAMPLER) ii.sampler=sampler;
            else {ii.imageView=images.at(d["resource"].get<std::string>()).views.at(d["mip"].get<size_t>()); ii.imageLayout=images.at(d["resource"].get<std::string>()).layout;}
            VkWriteDescriptorSet w{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET}; w.dstSet=pass.set; w.dstBinding=d["binding"]; w.descriptorCount=1; w.descriptorType=type; w.pImageInfo=&ii;
            vkUpdateDescriptorSets(device,1,&w,0,nullptr);
        }
        passes.push_back(pass);
    }
    void makeGraphics(Pass& pass,const json& p,VkShaderModule fragment,const std::string& entry) {
        auto bytes=read("fullscreen_vertex.spv"); std::vector<uint32_t> words(bytes.size()/4); memcpy(words.data(),bytes.data(),bytes.size());
        VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; mi.codeSize=bytes.size(); mi.pCode=words.data();
        VkShaderModule vertex; VK(vkCreateShaderModule(device,&mi,nullptr,&vertex)); modules.push_back(vertex);
        VkAttachmentDescription attachment{}; attachment.format=VkFormat(p.value("attachment_format",int(VK_FORMAT_R8G8B8A8_SRGB))); attachment.samples=VK_SAMPLE_COUNT_1_BIT;
        attachment.loadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE; attachment.storeOp=VK_ATTACHMENT_STORE_OP_STORE;
        attachment.stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE; attachment.stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE;
        attachment.initialLayout=attachment.finalLayout=VK_IMAGE_LAYOUT_GENERAL;
        VkAttachmentReference ref{0,VK_IMAGE_LAYOUT_GENERAL};
        VkSubpassDescription sub{}; sub.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS; sub.colorAttachmentCount=1; sub.pColorAttachments=&ref;
        VkRenderPassCreateInfo ri{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO}; ri.attachmentCount=1; ri.pAttachments=&attachment; ri.subpassCount=1; ri.pSubpasses=&sub;
        VK(vkCreateRenderPass(device,&ri,nullptr,&pass.renderPass));
        auto view=images.at(p["attachment"].get<std::string>()).views[0];
        VkFramebufferCreateInfo fi{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO}; fi.renderPass=pass.renderPass; fi.attachmentCount=1; fi.pAttachments=&view; fi.width=pass.width; fi.height=pass.height; fi.layers=1;
        VK(vkCreateFramebuffer(device,&fi,nullptr,&pass.framebuffer));
        VkPipelineShaderStageCreateInfo stages[2]={{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO},{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}};
        stages[0].stage=VK_SHADER_STAGE_VERTEX_BIT; stages[0].module=vertex; stages[0].pName="fullscreen_vertex";
        stages[1].stage=VK_SHADER_STAGE_FRAGMENT_BIT; stages[1].module=fragment; stages[1].pName=entry.c_str();
        VkPipelineVertexInputStateCreateInfo vi{VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
        VkPipelineInputAssemblyStateCreateInfo ia{VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO}; ia.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
        VkViewport viewport{0,0,float(pass.width),float(pass.height),0,1}; VkRect2D scissor{{0,0},{pass.width,pass.height}};
        VkPipelineViewportStateCreateInfo vs{VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO}; vs.viewportCount=1; vs.pViewports=&viewport; vs.scissorCount=1; vs.pScissors=&scissor;
        VkPipelineRasterizationStateCreateInfo rs{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO}; rs.polygonMode=VK_POLYGON_MODE_FILL; rs.cullMode=VK_CULL_MODE_NONE; rs.frontFace=VK_FRONT_FACE_COUNTER_CLOCKWISE; rs.lineWidth=1;
        VkPipelineMultisampleStateCreateInfo ms{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO}; ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
        VkPipelineColorBlendAttachmentState cb{}; cb.colorWriteMask=15;
        VkPipelineColorBlendStateCreateInfo blend{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO}; blend.attachmentCount=1; blend.pAttachments=&cb;
        VkGraphicsPipelineCreateInfo gi{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO}; gi.stageCount=2; gi.pStages=stages;
        gi.pVertexInputState=&vi; gi.pInputAssemblyState=&ia; gi.pViewportState=&vs; gi.pRasterizationState=&rs; gi.pMultisampleState=&ms; gi.pColorBlendState=&blend;
        gi.layout=pass.layout; gi.renderPass=pass.renderPass;
        VK(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&gi,nullptr,&pass.pipeline));
    }
    void dispatch(const Pass& p) {
        if(p.graphics) {
            VkRenderPassBeginInfo bi{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO}; bi.renderPass=p.renderPass; bi.framebuffer=p.framebuffer; bi.renderArea={{0,0},{p.width,p.height}};
            vkCmdBeginRenderPass(cmd,&bi,VK_SUBPASS_CONTENTS_INLINE);
            vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,p.pipeline);
            vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,p.layout,0,1,&p.set,0,nullptr);
            vkCmdDraw(cmd,3,1,0,0); vkCmdEndRenderPass(cmd); return;
        }
        vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.pipeline);
        vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.layout,0,1,&p.set,0,nullptr);
        vkCmdDispatch(cmd,p.x,p.y,1);
    }
    // Separate whole-chain and diagnostic modes: per-pass timestamps serialize
    // stages more than the ordinary chain and must not supply headline totals.
    void record(bool baseline,bool diagnostic,const Pass* prefix=nullptr,int prefixDraws=1) {
        begin(); vkCmdResetQueryPool(cmd,queries,0,2*productionCount+2); barrier();
        vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queries,0);
        // Optional renderer-style submission: headline timestamps include the
        // common graphics producer in BOTH Fusion and baseline measurements.
        if(prefix) {
            bool nextGraphics=false;
            for(const auto& p:passes)if(p.baseline==baseline){nextGraphics=p.graphics;break;}
            for(int i=0;i<prefixDraws;i++){dispatch(*prefix);barrier(true,i+1<prefixDraws?true:nextGraphics);}
        }
        uint32_t index=0;
        for(size_t i=0;i<passes.size();i++) if(passes[i].baseline==baseline) {
            const auto& p=passes[i]; bool nextGraphics=p.graphics;
            for(size_t j=i+1;j<passes.size();j++) if(passes[j].baseline==baseline) {nextGraphics=passes[j].graphics;break;}
            if(diagnostic) vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,queries,2+2*index);
            dispatch(p); barrier(p.graphics,nextGraphics);
            if(diagnostic) vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queries,3+2*index);
            index++;
        }
        vkCmdWriteTimestamp(cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,queries,1);
        VK(vkEndCommandBuffer(cmd));
    }
    std::vector<double> execute(uint32_t queryCount,VkSemaphore waitSemaphore=VK_NULL_HANDLE,VkSemaphore signalSemaphore=VK_NULL_HANDLE) {
        auto hostStart=std::chrono::steady_clock::now();
        VK(vkResetFences(device,1,&fence)); VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO}; si.commandBufferCount=1; si.pCommandBuffers=&cmd;
        VkPipelineStageFlags waitStage=VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
        if(waitSemaphore){si.waitSemaphoreCount=1;si.pWaitSemaphores=&waitSemaphore;si.pWaitDstStageMask=&waitStage;}
        if(signalSemaphore){si.signalSemaphoreCount=1;si.pSignalSemaphores=&signalSemaphore;}
        VK(vkQueueSubmit(queue,1,&si,fence)); VK(vkWaitForFences(device,1,&fence,VK_TRUE,60000000000ull));
        std::vector<uint64_t> ticks(queryCount); VK(vkGetQueryPoolResults(device,queries,0,queryCount,ticks.size()*8,ticks.data(),8,VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WAIT_BIT));
        const uint64_t mask=validBits==64?~uint64_t(0):(uint64_t(1)<<validBits)-1;
        std::vector<double> ms; for(size_t i=0;i<ticks.size();i+=2) ms.push_back(double((ticks[i+1]-ticks[i])&mask)*properties.limits.timestampPeriod/1e6);
        lastSubmitQueryMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-hostStart).count();
        return ms;
    }
    json measure(int warmup,int frames,int rounds,double intervalMs) {
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
            json samples=json::array(), hostSamples=json::array();
            for(int i=-warmup;i<frames;i++) {
                auto start=std::chrono::steady_clock::now(); auto v=execute(2);
                if(i>=0) {samples.push_back(v[0]); hostSamples.push_back(lastSubmitQueryMs);}
                if(intervalMs>0) std::this_thread::sleep_until(start+std::chrono::duration<double,std::milli>(intervalMs));
            }
            result["blocks"].push_back({{"round",round},{"kind",baseline?"baseline":"fusion"},{"gpu_ms",samples},{"cpu_submit_wait_query_ms",hostSamples}});
            std::cerr<<"Round "<<round<<" "<<(baseline?"baseline":"fusion")<<" complete\n";
        }
        record(false,true); for(int i=0;i<warmup;i++) execute(2+2*productionCount);
        result["diagnostic_ms"]=json::array();
        for(int i=0;i<frames;i++) {
            auto start=std::chrono::steady_clock::now(); result["diagnostic_ms"].push_back(execute(2+2*productionCount));
            if(intervalMs) std::this_thread::sleep_until(start+std::chrono::duration<double,std::milli>(intervalMs));
        }
        return result;
    }
    void dump() {
        // Last execution is Fusion; reference readback happens after all timing.
        begin(); VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; mb.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT|VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT; mb.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
        vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,1,&mb,0,nullptr,0,nullptr);
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
        for(size_t i=0;i<passes.size();i++) if(!passes[i].baseline) {
            const auto& p=passes[i]; bool nextGraphics=p.graphics;
            for(size_t j=i+1;j<passes.size();j++) if(!passes[j].baseline) {nextGraphics=passes[j].graphics;break;}
            dispatch(p); barrier(p.graphics,nextGraphics);
        }
        submit(); dump();
    }
    ~Runner() {
        if(!device) return; vkDeviceWaitIdle(device);
        for(auto& p:passes) {vkDestroyPipeline(device,p.pipeline,nullptr); vkDestroyPipelineLayout(device,p.layout,nullptr); vkDestroyDescriptorSetLayout(device,p.setLayout,nullptr);
            if(p.graphics) {vkDestroyFramebuffer(device,p.framebuffer,nullptr); vkDestroyRenderPass(device,p.renderPass,nullptr);}}
        for(auto m:modules) vkDestroyShaderModule(device,m,nullptr);
        for(auto& [name,im]:images) {for(auto v:im.views) vkDestroyImageView(device,v,nullptr); vkDestroyImage(device,im.image,nullptr); vkFreeMemory(device,im.memory,nullptr);}
        for(auto& b:buffers) {vkDestroyBuffer(device,b.buffer,nullptr); vkFreeMemory(device,b.memory,nullptr);}
        vkDestroyQueryPool(device,queries,nullptr); vkDestroyDescriptorPool(device,descriptors,nullptr); vkDestroySampler(device,sampler,nullptr);
        vkDestroyFence(device,fence,nullptr); if(graphicsPool!=pool)vkDestroyCommandPool(device,graphicsPool,nullptr); vkDestroyCommandPool(device,pool,nullptr); vkDestroyDevice(device,nullptr); vkDestroyInstance(instance,nullptr);
    }
};
#ifndef LOCAL_EXPOSURE_RUNNER_LIBRARY
int main(int argc,char** argv) {
    try {
        int warmup=argc>1?std::stoi(argv[1]):60, frames=argc>2?std::stoi(argv[2]):120;
        int rounds=argc>3?std::stoi(argv[3]):3;
        double interval=argc>4?std::stod(argv[4]):16.;
        if(warmup<0||frames<1||rounds<1||interval<0) throw std::runtime_error("Invalid run counts");
        bool reference=argc>5 && std::string(argv[5])=="verify";
        Runner r; std::cerr<<r.properties.deviceName<<"\n"; r.load(reference);
        if(reference) {r.verify(); return 0;}
        auto result=r.measure(warmup,frames,rounds,interval); r.dump();
        std::ofstream("timings.json")<<result.dump(2)<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n"; return 1;}
}
#endif
