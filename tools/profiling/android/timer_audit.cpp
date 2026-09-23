// Timer validation is separate from the production benchmark. It uses the
// same Vulkan setup/query conversion and a bundle whose first pass is empty.
#define LOCAL_EXPOSURE_RUNNER_LIBRARY
#include "runner.cpp"

static void recordAudit(Runner& r,int kind,uint32_t gx,uint32_t gy,int repeats,bool dependency) {
    r.begin(); vkCmdResetQueryPool(r.cmd,r.queries,0,2); r.barrier();
    vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,r.queries,0);
    for(int i=0;i<repeats;i++) {
        if(kind) {
            auto& p=r.passes.at(kind==1?0:1);
            vkCmdBindPipeline(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.pipeline);
            vkCmdBindDescriptorSets(r.cmd,VK_PIPELINE_BIND_POINT_COMPUTE,p.layout,0,1,&p.set,0,nullptr);
            vkCmdDispatch(r.cmd,gx,gy,1);
        }
        if(dependency) r.barrier();
    }
    vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,r.queries,1);
    VK(vkEndCommandBuffer(r.cmd));
}

static json sample(Runner& r,const char* name,int kind,uint32_t gx,uint32_t gy,int repeats,bool dependency) {
    recordAudit(r,kind,gx,gy,repeats,dependency);
    for(int i=0;i<40;i++) r.execute(2);
    json result={{"name",name},{"groups",{gx,gy}},{"repeats",repeats},{"dependency",dependency},
                 {"gpu_ms",json::array()},{"cpu_ms",json::array()},{"ticks",json::array()}};
    for(int i=0;i<100;i++) {
        auto ms=r.execute(2); result["gpu_ms"].push_back(ms[0]); result["cpu_ms"].push_back(r.lastSubmitQueryMs);
        uint64_t ticks[2]; VK(vkGetQueryPoolResults(r.device,r.queries,0,2,sizeof(ticks),ticks,8,VK_QUERY_RESULT_64_BIT|VK_QUERY_RESULT_WAIT_BIT));
        result["ticks"].push_back({ticks[0],ticks[1]});
    }
    std::cerr<<name<<" complete\n"; return result;
}

static json calibratedClock(Runner& r) {
    if(r.calibrationExtension.empty()) return {{"available",false}};
    auto domains=reinterpret_cast<PFN_vkGetPhysicalDeviceCalibrateableTimeDomainsEXT>(vkGetInstanceProcAddr(r.instance,"vkGetPhysicalDeviceCalibrateableTimeDomainsEXT"));
    auto capture=reinterpret_cast<PFN_vkGetCalibratedTimestampsEXT>(vkGetDeviceProcAddr(r.device,"vkGetCalibratedTimestampsEXT"));
    if(!domains||!capture) throw std::runtime_error("Calibration extension has no entry points");
    uint32_t count=0; VK(domains(r.physical,&count,nullptr)); std::vector<VkTimeDomainEXT> supported(count); VK(domains(r.physical,&count,supported.data()));
    VkTimeDomainEXT host=VK_TIME_DOMAIN_DEVICE_EXT;
    for(auto domain:supported) if(domain==VK_TIME_DOMAIN_CLOCK_MONOTONIC_EXT || domain==VK_TIME_DOMAIN_CLOCK_MONOTONIC_RAW_EXT) host=domain;
    if(host==VK_TIME_DOMAIN_DEVICE_EXT) throw std::runtime_error("No nanosecond host calibration domain");
    VkCalibratedTimestampInfoEXT info[2]={{VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT,nullptr,VK_TIME_DOMAIN_DEVICE_EXT},
                                      {VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT,nullptr,host}};
    json samples=json::array();
    for(int i=0;i<7;i++) {
        uint64_t ts[2],deviation; VK(capture(r.device,2,info,ts,&deviation));
        samples.push_back({{"device_ticks",ts[0]},{"host_ns",ts[1]},{"max_deviation_ns",deviation}});
        if(i<6) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return {{"available",true},{"host_domain",int(host)},{"samples",samples}};
}

int main(int argc,char** argv) {
    try {
        bool calibration=argc>1 && std::string(argv[1])=="calibrated";
        Runner r(calibration); r.load();
        if(r.passes.size()!=2 || r.passes[0].label!="empty_probe") throw std::runtime_error("Expected empty + baseline diagnostic bundle");
        json report={{"gpu",r.properties.deviceName},{"timestamp_period_ns",r.properties.limits.timestampPeriod},
            {"timestamp_valid_bits",r.validBits},{"calibration_extension",r.calibrationExtension}};
        report["calibrated_clock"]=calibratedClock(r);
        report["cases"]=json::array();
        report["cases"].push_back(sample(r,"timestamps_only",0,0,0,0,false));
        report["cases"].push_back(sample(r,"barrier_only",0,0,0,1,true));
        report["cases"].push_back(sample(r,"empty_one_group",1,1,1,1,true));
        report["cases"].push_back(sample(r,"empty_8160_groups",1,120,68,1,true));
        report["cases"].push_back(sample(r,"empty_32400_groups",1,240,135,1,true));
        report["cases"].push_back(sample(r,"empty_32400_groups_no_barrier",1,240,135,1,false));
        report["cases"].push_back(sample(r,"empty_32400_groups_x16",1,240,135,16,true));
        report["cases"].push_back(sample(r,"tonemap_x1",2,240,135,1,true));
        report["cases"].push_back(sample(r,"tonemap_x16",2,240,135,16,true));
        report["cases"].push_back(sample(r,"timestamps_only_after_load",0,0,0,0,false));
        report["calibrated_clock_after"]=calibratedClock(r);
        std::ofstream("timer-audit.json")<<report.dump(2)<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n"; return 1;}
}
