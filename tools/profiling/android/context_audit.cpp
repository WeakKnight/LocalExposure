#define LOCAL_EXPOSURE_RUNNER_LIBRARY
#include "runner.cpp"
int main(int argc,char** argv) {
    try {
        Runner r; r.load();
        Pass context=r.passes.back(); r.passes.pop_back(); r.productionCount--;
        VkCommandBuffer chain=r.cmd, contextCmd;
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
        ai.commandPool=r.pool; ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ai.commandBufferCount=1;
        VK(vkAllocateCommandBuffers(r.device,&ai,&contextCmd));
        r.cmd=contextCmd; r.begin(); vkCmdResetQueryPool(r.cmd,r.queries,0,2);
        vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,r.queries,0);
        r.dispatch(context); r.barrier(true,false);
        vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,r.queries,1);
        VK(vkEndCommandBuffer(r.cmd));
        json result={{"device",r.properties.deviceName},{"contract","Graphics context is a separate completed submission immediately before each measured chain; its cost is recorded separately, not included in chain timestamps."}};
        result["blocks"]=json::array();
        const int warmup=30,frames=90;
        for(int round=0;round<3;round++) for(int modeIndex=0;modeIndex<2;modeIndex++) for(int phase=0;phase<2;phase++) {
            bool preceding=(round+modeIndex)%2!=0, baseline=(round+phase)%2!=0;
            r.cmd=chain; r.record(baseline,false);
            json values=json::array(),graphics=json::array(),host=json::array();
            for(int i=-warmup;i<frames;i++) {
                auto start=std::chrono::steady_clock::now(); double graphicsMs=0;
                if(preceding) {r.cmd=contextCmd; graphicsMs=r.execute(2)[0];}
                r.cmd=chain; auto times=r.execute(2);
                if(i>=0) {values.push_back(times[0]); graphics.push_back(graphicsMs); host.push_back(r.lastSubmitQueryMs);}
                std::this_thread::sleep_until(start+std::chrono::duration<double,std::milli>(1000./45.));
            }
            result["blocks"].push_back({{"round",round},{"preceding_graphics",preceding},{"kind",baseline?"baseline":"fusion"},{"gpu_ms",values},{"preceding_graphics_ms",graphics},{"cpu_submit_wait_query_ms",host}});
            std::cerr<<round<<" preceding="<<preceding<<" baseline="<<baseline<<" complete\n";
        }
        r.cmd=chain; r.record(false,false); r.execute(2); r.dump();
        r.passes.push_back(context); // Own and destroy the extra pipeline normally.
        std::ofstream("context.json")<<result.dump(2)<<"\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;}
}
