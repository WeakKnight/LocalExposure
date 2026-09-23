// Sequential buffer-copy bandwidth with three rotating disjoint buffer pairs.
// No input upload/readback/initialization in the timestamp intervals.
#define LOCAL_EXPOSURE_RUNNER_LIBRARY
#include "runner.cpp"

static Buffer gpuBuffer(Runner& r,VkDeviceSize bytes) {
    Buffer b; b.size=bytes;
    VkBufferCreateInfo ci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO}; ci.size=bytes;
    ci.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    VK(vkCreateBuffer(r.device,&ci,nullptr,&b.buffer));
    VkMemoryRequirements req; vkGetBufferMemoryRequirements(r.device,b.buffer,&req);
    VkMemoryAllocateInfo ai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO}; ai.allocationSize=req.size;
    ai.memoryTypeIndex=r.memoryType(req.memoryTypeBits,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    VK(vkAllocateMemory(r.device,&ai,nullptr,&b.memory)); VK(vkBindBufferMemory(r.device,b.buffer,b.memory,0));
    r.buffers.push_back(b); return b;
}

static VkPipeline pipeline(Runner& r,VkPipelineLayout layout,const char* entry) {
    auto bytes=read(std::string(entry)+".spv"); std::vector<uint32_t> words(bytes.size()/4); memcpy(words.data(),bytes.data(),bytes.size());
    VkShaderModuleCreateInfo mi{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; mi.codeSize=bytes.size(); mi.pCode=words.data();
    VkShaderModule module; VK(vkCreateShaderModule(r.device,&mi,nullptr,&module)); r.modules.push_back(module);
    VkComputePipelineCreateInfo ci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO}; ci.layout=layout;
    ci.stage={VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO}; ci.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT; ci.stage.module=module; ci.stage.pName=entry;
    VkPipeline result; VK(vkCreateComputePipelines(r.device,VK_NULL_HANDLE,1,&ci,nullptr,&result)); return result;
}

static uint32_t hashWord(uint32_t x) {x^=x>>16; x*=0x7feb352du; x^=x>>15; x*=0x846ca68bu; return x^(x>>16);}

int main(int argc,char** argv) {
    try {
        // Arguments: bytes per buffer, pairs, samples, warmup, pacing.
        uint64_t bytes=argc>1?std::stoull(argv[1]):33554432;
        uint32_t pairs=argc>2?std::stoul(argv[2]):3;
        int frames=argc>3?std::stoi(argv[3]):120,warmup=argc>4?std::stoi(argv[4]):60,interval=argc>5?std::stoi(argv[5]):0;
        if(bytes<4096 || bytes%4096 || bytes>134217728 || pairs<1 || pairs>3 || frames<1 || warmup<0 || interval<0)
            throw std::runtime_error("Invalid bandwidth configuration");
        Runner r;
        if(bytes>r.properties.limits.maxStorageBufferRange) throw std::runtime_error("Storage buffer range exceeds device limit");
        uint32_t elements=uint32_t(bytes/16),groups=(elements+255)/256;
        if(groups>r.properties.limits.maxComputeWorkGroupCount[0]) throw std::runtime_error("Dispatch exceeds device limit");
        std::vector<char> cb(256); memcpy(cb.data(),&elements,4); auto uniform=r.buffer(cb.size(),VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,&cb);
        VkDescriptorSetLayoutBinding bindings[]={{0,VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr},
            {1,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr},{2,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr}};
        VkDescriptorSetLayoutCreateInfo li{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO}; li.bindingCount=3; li.pBindings=bindings;
        VkDescriptorSetLayout setLayout; VK(vkCreateDescriptorSetLayout(r.device,&li,nullptr,&setLayout));
        VkPipelineLayoutCreateInfo pi{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; pi.setLayoutCount=1; pi.pSetLayouts=&setLayout;
        VkPipelineLayout layout; VK(vkCreatePipelineLayout(r.device,&pi,nullptr,&layout));
        VkDescriptorPoolSize poolSizes[]={{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER,pairs},{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,2*pairs}};
        VkDescriptorPoolCreateInfo di{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO}; di.maxSets=pairs; di.poolSizeCount=2; di.pPoolSizes=poolSizes;
        VkDescriptorPool descriptorPool; VK(vkCreateDescriptorPool(r.device,&di,nullptr,&descriptorPool));
        auto init=pipeline(r,layout,"initialize"),copy=pipeline(r,layout,"stream_copy");
        std::vector<Buffer> src,dst; std::vector<VkDescriptorSet> sets;
        for(uint32_t i=0;i<pairs;i++) {
            src.push_back(gpuBuffer(r,bytes)); dst.push_back(gpuBuffer(r,bytes));
            VkDescriptorSetAllocateInfo ai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO}; ai.descriptorPool=descriptorPool; ai.descriptorSetCount=1; ai.pSetLayouts=&setLayout;
            VkDescriptorSet set; VK(vkAllocateDescriptorSets(r.device,&ai,&set)); sets.push_back(set);
            VkDescriptorBufferInfo bi[]={{uniform.buffer,0,256},{src.back().buffer,0,bytes},{dst.back().buffer,0,bytes}};
            for(uint32_t b=0;b<3;b++) {
                VkWriteDescriptorSet wi{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET}; wi.dstSet=set; wi.dstBinding=b; wi.descriptorCount=1;
                wi.descriptorType=b?VK_DESCRIPTOR_TYPE_STORAGE_BUFFER:VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER; wi.pBufferInfo=&bi[b];
                vkUpdateDescriptorSets(r.device,1,&wi,0,nullptr);
            }
        }
        r.begin();
        for(uint32_t i=0;i<pairs;i++) {
            vkCmdBindPipeline(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,init);
            vkCmdBindDescriptorSets(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&sets[i],0,nullptr);
            vkCmdDispatch(r.cmd,groups,1,1);
            vkCmdFillBuffer(r.cmd,dst[i].buffer,0,bytes,0);
        }
        VkMemoryBarrier ready{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; ready.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT|VK_ACCESS_TRANSFER_WRITE_BIT;
        ready.dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT|VK_ACCESS_TRANSFER_READ_BIT|VK_ACCESS_TRANSFER_WRITE_BIT;
        vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&ready,0,nullptr,0,nullptr); r.submit();
        VkQueryPoolCreateInfo qi{VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO}; qi.queryType=VK_QUERY_TYPE_TIMESTAMP; qi.queryCount=2;
        VK(vkCreateQueryPool(r.device,&qi,nullptr,&r.queries));
        json report={{"gpu",r.properties.deviceName},{"driver_version",r.properties.driverVersion},
            {"timestamp_period_ns",r.properties.limits.timestampPeriod},{"bytes_per_buffer",bytes},{"pairs",pairs},
            {"working_set_bytes",2*bytes*pairs},{"payload_bytes_per_sample",2*bytes*pairs},{"interval_ms",interval},
            {"warmup_submissions",warmup},{"frames",frames},{"blocks",json::array()}};
        uint32_t extensionCount=0; VK(vkEnumerateDeviceExtensionProperties(r.physical,nullptr,&extensionCount,nullptr));
        std::vector<VkExtensionProperties> extensions(extensionCount); VK(vkEnumerateDeviceExtensionProperties(r.physical,nullptr,&extensionCount,extensions.data()));
        report["performance_query_extensions"]=json::array();
        for(auto& e:extensions) if(std::string(e.extensionName).find("performance_query")!=std::string::npos) report["performance_query_extensions"].push_back(e.extensionName);
        // Compute/transfer ABBA, preserving all copies between timestamp writes.
        for(int block=0;block<4;block++) {
            bool transfer=block==1||block==2;
            r.begin(); vkCmdResetQueryPool(r.cmd,r.queries,0,2);
            vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&ready,0,nullptr,0,nullptr);
            vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,r.queries,0);
            for(uint32_t i=0;i<pairs;i++) {
                if(transfer) {VkBufferCopy region{0,0,bytes}; vkCmdCopyBuffer(r.cmd,src[i].buffer,dst[i].buffer,1,&region);}
                else {
                    vkCmdBindPipeline(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,copy);
                    vkCmdBindDescriptorSets(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&sets[i],0,nullptr);
                    vkCmdDispatch(r.cmd,groups,1,1);
                }
            }
            // Include write completion/visibility, not just dispatch issuance.
            vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,0,1,&ready,0,nullptr,0,nullptr);
            vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,r.queries,1); VK(vkEndCommandBuffer(r.cmd));
            json samples=json::array(),host=json::array();
            for(int f=-warmup;f<frames;f++) {
                auto start=std::chrono::steady_clock::now(); auto ms=r.execute(2);
                if(f>=0) {samples.push_back(ms[0]); host.push_back(r.lastSubmitQueryMs);}
                if(interval) std::this_thread::sleep_until(start+std::chrono::milliseconds(interval));
            }
            // Full buffer validation, after each mode, outside GPU timing.
            auto readback=r.buffer(bytes,VK_BUFFER_USAGE_TRANSFER_DST_BIT);
            uint64_t mismatches=0;
            for(uint32_t i=0;i<pairs;i++) {
                r.begin(); VkBufferCopy region{0,0,bytes}; vkCmdCopyBuffer(r.cmd,dst[i].buffer,readback.buffer,1,&region);
                VkMemoryBarrier hostReady{VK_STRUCTURE_TYPE_MEMORY_BARRIER}; hostReady.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; hostReady.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
                vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&hostReady,0,nullptr,0,nullptr); r.submit();
                void* mapped; VK(vkMapMemory(r.device,readback.memory,0,bytes,0,&mapped));
                auto words=static_cast<const uint32_t*>(mapped); for(uint32_t w=0;w<bytes/4;w++) if(words[w]!=hashWord(w)) mismatches++;
                vkUnmapMemory(r.device,readback.memory);
            }
            report["blocks"].push_back({{"mode",transfer?"transfer_copy":"compute_copy"},{"gpu_ms",samples},{"cpu_ms",host},{"mismatches",mismatches}});
            if(mismatches) throw std::runtime_error("Bandwidth copy validation failed");
            std::cerr<<(transfer?"transfer":"compute")<<" block "<<block<<" validated\n";
            // readback commands replaced r.cmd; next block records its own loop.
        }
        std::ofstream("bandwidth.json")<<report.dump(2)<<"\n";
        vkDestroyPipeline(r.device,init,nullptr); vkDestroyPipeline(r.device,copy,nullptr);
        vkDestroyPipelineLayout(r.device,layout,nullptr); vkDestroyDescriptorPool(r.device,descriptorPool,nullptr); vkDestroyDescriptorSetLayout(r.device,setLayout,nullptr);
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}
}
