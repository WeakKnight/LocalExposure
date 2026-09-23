#define VK_USE_PLATFORM_ANDROID_KHR
#define LOCAL_EXPOSURE_RUNNER_LIBRARY
#include "runner.cpp"
#include <android/native_activity.h>
#include <android/window.h>
#include <android/asset_manager.h>
#include <android/log.h>
#include <atomic>
#include <sys/stat.h>
#include <unistd.h>

struct ActivityState { ANativeActivity* activity; std::thread worker; std::atomic<bool> stop{false}; };
static void extractBundle(ANativeActivity* a) {
    mkdir(a->internalDataPath,0700); if(chdir(a->internalDataPath)) throw std::runtime_error("chdir app files failed");
    AAssetDir* dir=AAssetManager_openDir(a->assetManager,"bundle");
    while(const char* name=AAssetDir_getNextFileName(dir)) {
        std::string path=std::string("bundle/")+name;
        AAsset* asset=AAssetManager_open(a->assetManager,path.c_str(),AASSET_MODE_STREAMING);
        if(!asset) throw std::runtime_error("Cannot read asset "+path);
        std::ofstream f(name,std::ios::binary); char buffer[65536];int count;
        while((count=AAsset_read(asset,buffer,sizeof(buffer)))>0) f.write(buffer,count);
        AAsset_close(asset);
    }
    AAssetDir_close(dir);
}

struct Display {
    Runner& r; VkSurfaceKHR surface{}; VkSwapchainKHR swapchain{};
    VkExtent2D extent{};VkFormat format{};std::vector<VkImage> images;
    VkSemaphore acquired{},ready{};VkCommandBuffer post{};
    Display(Runner& runner,ANativeWindow* window):r(runner) {
        VkAndroidSurfaceCreateInfoKHR si{VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR};si.window=window;
        VK(vkCreateAndroidSurfaceKHR(r.instance,&si,nullptr,&surface));
        VkBool32 supported;VK(vkGetPhysicalDeviceSurfaceSupportKHR(r.physical,r.graphicsFamily,surface,&supported));
        if(!supported) throw std::runtime_error("Selected queue cannot present");
        VkSurfaceCapabilitiesKHR caps;VK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(r.physical,surface,&caps));
        uint32_t n;VK(vkGetPhysicalDeviceSurfaceFormatsKHR(r.physical,surface,&n,nullptr));
        std::vector<VkSurfaceFormatKHR> formats(n);VK(vkGetPhysicalDeviceSurfaceFormatsKHR(r.physical,surface,&n,formats.data()));
        auto chosen=formats[0];bool found=false;
        for(auto f:formats) if(f.format==VK_FORMAT_R8G8B8A8_SRGB) {chosen=f;found=true;break;}
        if(!found) throw std::runtime_error("Actual surface does not offer RGBA8 sRGB");
        format=chosen.format;extent=caps.currentExtent;
        if(extent.width==UINT32_MAX) extent={uint32_t(ANativeWindow_getWidth(window)),uint32_t(ANativeWindow_getHeight(window))};
        if(!(caps.supportedUsageFlags&VK_IMAGE_USAGE_TRANSFER_DST_BIT)) throw std::runtime_error("Surface lacks transfer destination usage");
        VkSwapchainCreateInfoKHR ci{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};ci.surface=surface;
        ci.minImageCount=std::max(3u,caps.minImageCount);if(caps.maxImageCount)ci.minImageCount=std::min(ci.minImageCount,caps.maxImageCount);
        ci.imageFormat=chosen.format;ci.imageColorSpace=chosen.colorSpace;ci.imageExtent=extent;ci.imageArrayLayers=1;
        ci.imageUsage=VK_IMAGE_USAGE_TRANSFER_DST_BIT;ci.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;
        ci.preTransform=caps.currentTransform;ci.compositeAlpha=(caps.supportedCompositeAlpha&VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR)?VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR:VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR;
        ci.presentMode=VK_PRESENT_MODE_FIFO_KHR;ci.clipped=VK_TRUE;
        VK(vkCreateSwapchainKHR(r.device,&ci,nullptr,&swapchain));
        VK(vkGetSwapchainImagesKHR(r.device,swapchain,&n,nullptr));images.resize(n);VK(vkGetSwapchainImagesKHR(r.device,swapchain,&n,images.data()));
        VkSemaphoreCreateInfo sem{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};VK(vkCreateSemaphore(r.device,&sem,nullptr,&acquired));VK(vkCreateSemaphore(r.device,&sem,nullptr,&ready));
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=r.graphicsPool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;
        VK(vkAllocateCommandBuffers(r.device,&ai,&post));
        std::ofstream("surface.json")<<json({{"width",extent.width},{"height",extent.height},{"format",int(format)},{"supported_usage",caps.supportedUsageFlags},{"storage_supported",bool(caps.supportedUsageFlags&VK_IMAGE_USAGE_STORAGE_BIT)}}).dump(2);
    }
    void present(const Image& source,VkSemaphore computeDone=VK_NULL_HANDLE,VkSemaphore graphicsReady=VK_NULL_HANDLE) {
        uint32_t index;VkResult acquiredResult=vkAcquireNextImageKHR(r.device,swapchain,10000000000ull,acquired,VK_NULL_HANDLE,&index);
        if(acquiredResult!=VK_SUCCESS && acquiredResult!=VK_SUBOPTIMAL_KHR) throw std::runtime_error("Acquire failed "+std::to_string(acquiredResult));
        auto main=r.cmd;auto mainQueue=r.queue;r.queue=r.graphicsQueue;r.cmd=post;r.begin();
        VkMemoryBarrier mb{VK_STRUCTURE_TYPE_MEMORY_BARRIER};mb.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT;mb.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
        vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,1,&mb,0,nullptr,0,nullptr);
        VkImageMemoryBarrier ib{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};ib.image=images[index];ib.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED;ib.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        ib.srcQueueFamilyIndex=ib.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;ib.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};ib.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;
        vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&ib);
        VkImageBlit region{};region.srcSubresource=region.dstSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1};
        region.srcOffsets[1]={int32_t(source.width),int32_t(source.height),1};region.dstOffsets[1]={int32_t(extent.width),int32_t(extent.height),1};
        vkCmdBlitImage(r.cmd,source.image,VK_IMAGE_LAYOUT_GENERAL,images[index],VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,1,&region,VK_FILTER_LINEAR);
        ib.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;ib.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;ib.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;ib.dstAccessMask=0;
        vkCmdPipelineBarrier(r.cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,0,nullptr,1,&ib);
        VK(vkEndCommandBuffer(r.cmd));VK(vkResetFences(r.device,1,&r.fence));
        VkPipelineStageFlags waits[]={VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT};
        VkSemaphore waitSemaphores[]={acquired,computeDone},signals[]={ready,graphicsReady};
        VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.waitSemaphoreCount=computeDone?2:1;si.pWaitSemaphores=waitSemaphores;si.pWaitDstStageMask=waits;
        si.commandBufferCount=1;si.pCommandBuffers=&r.cmd;si.signalSemaphoreCount=graphicsReady?2:1;si.pSignalSemaphores=signals;
        VK(vkQueueSubmit(r.queue,1,&si,r.fence));
        VkPresentInfoKHR pi{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};pi.waitSemaphoreCount=1;pi.pWaitSemaphores=&ready;pi.swapchainCount=1;pi.pSwapchains=&swapchain;pi.pImageIndices=&index;
        VkResult presented=vkQueuePresentKHR(r.queue,&pi);if(presented!=VK_SUCCESS && presented!=VK_SUBOPTIMAL_KHR)throw std::runtime_error("Present failed");
        VK(vkWaitForFences(r.device,1,&r.fence,VK_TRUE,10000000000ull));
        // Queue completion makes semaphore reuse unambiguous for this diagnostic.
        VK(vkQueueWaitIdle(r.queue));r.cmd=main;r.queue=mainQueue;
    }
    ~Display() {vkDeviceWaitIdle(r.device);vkDestroySemaphore(r.device,acquired,nullptr);vkDestroySemaphore(r.device,ready,nullptr);vkDestroySwapchainKHR(r.device,swapchain,nullptr);vkDestroySurfaceKHR(r.instance,surface,nullptr);}
};

static void runActivity(ActivityState* state,ANativeWindow* window) {
    try {
        extractBundle(state->activity);std::ofstream("status.txt")<<"running";
        json settings;std::ifstream("activity.json")>>settings;
        const bool dedicated=settings.value("dedicated_compute",false),separate=settings.value("separate_queue",false);
        const bool crossQueue=dedicated||separate;
        const bool joint=settings.value("joint_submission",false);
        Runner r(false,true,separate,dedicated);r.load();Display display(r,window);
        VkQueue computeQueue=r.queue;VkSemaphore toGraphics{},toCompute{},toPresent{};
        if(crossQueue){
            VkSemaphoreCreateInfo si{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
            VK(vkCreateSemaphore(r.device,&si,nullptr,&toGraphics));VK(vkCreateSemaphore(r.device,&si,nullptr,&toCompute));VK(vkCreateSemaphore(r.device,&si,nullptr,&toPresent));
            VkSubmitInfo initial{VK_STRUCTURE_TYPE_SUBMIT_INFO};initial.signalSemaphoreCount=1;initial.pSignalSemaphores=&toGraphics;
            VK(vkQueueSubmit(computeQueue,1,&initial,VK_NULL_HANDLE));
        }
        Pass graphics=r.passes.back();r.passes.pop_back();r.productionCount--;
        VkCommandBuffer chain=r.cmd,context;
        VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=r.graphicsPool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;VK(vkAllocateCommandBuffers(r.device,&ai,&context));
        r.cmd=context;r.begin();vkCmdResetQueryPool(r.cmd,r.queries,0,2);
        vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,r.queries,0);
        for(int draw=0;draw<settings.value("graphics_draws",1);draw++){r.dispatch(graphics);r.barrier(true,true);}
        r.barrier(true,false);
        vkCmdWriteTimestamp(r.cmd,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,r.queries,1);VK(vkEndCommandBuffer(r.cmd));r.cmd=chain;
        json result={{"device",r.properties.deviceName},{"compute_family",r.family},{"graphics_family",r.graphicsFamily},{"config",settings},{"blocks",json::array()}};
        const int warmup=settings.value("warmup",30),frames=settings.value("frames",90),rounds=settings.value("rounds",3);
        const bool preceding=settings.value("graphics_context",true);
        for(int round=0;round<rounds && !state->stop;round++) for(int phase=0;phase<2 && !state->stop;phase++) {
            bool baseline=(round+phase)%2!=0;r.cmd=chain;r.record(baseline,false,joint?&graphics:nullptr,settings.value("graphics_draws",1));
            json samples=json::array(),cpu=json::array(),contextSamples=json::array(),wall=json::array();
            for(int i=-warmup;i<frames && !state->stop;i++) {
                auto start=std::chrono::steady_clock::now();double contextMs=0;
                if(preceding&&!joint) {r.cmd=context;r.queue=r.graphicsQueue;contextMs=r.execute(2,toGraphics,toCompute)[0];}
                r.cmd=chain;r.queue=computeQueue;auto t=r.execute(2,toCompute,toPresent);double hostMs=r.lastSubmitQueryMs;
                display.present(r.images.at(baseline?"baseline":"final"),toPresent,toGraphics);
                if(i>=0) {samples.push_back(t[0]);cpu.push_back(hostMs);contextSamples.push_back(contextMs);wall.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());}
                std::this_thread::sleep_until(start+std::chrono::duration<double,std::milli>(1000./settings.value("fps",45.)));
            }
            result["blocks"].push_back({{"round",round},{"kind",baseline?"baseline":"fusion"},{"gpu_ms",samples},{"cpu_ms",cpu},{"context_gpu_ms",contextSamples},{"frame_work_wall_ms",wall}});
            std::ofstream("activity-result.json")<<result.dump(2)<<"\n";
            std::ofstream("status.txt")<<"round "<<round<<" "<<(baseline?"baseline":"fusion");
        }
        result["passes"]=json::array();for(const auto& p:r.passes)if(!p.baseline)result["passes"].push_back(p.label);
        r.cmd=chain;r.record(false,true,joint?&graphics:nullptr,settings.value("graphics_draws",1));result["diagnostic_ms"]=json::array();
        for(int i=-10;i<30 && !state->stop;i++) {
            auto start=std::chrono::steady_clock::now();
            if(preceding&&!joint){r.cmd=context;r.queue=r.graphicsQueue;r.execute(2,toGraphics,toCompute);}
            r.cmd=chain;r.queue=computeQueue;auto times=r.execute(2+2*r.productionCount,toCompute,toPresent);
            if(i>=0)result["diagnostic_ms"].push_back(times);
            display.present(r.images.at("final"),toPresent,toGraphics);
            std::this_thread::sleep_until(start+std::chrono::duration<double,std::milli>(1000./settings.value("fps",45.)));
        }
        r.cmd=chain;r.record(false,false);r.execute(2);r.dump();r.passes.push_back(graphics);
        vkDeviceWaitIdle(r.device);if(toGraphics)vkDestroySemaphore(r.device,toGraphics,nullptr);if(toCompute)vkDestroySemaphore(r.device,toCompute,nullptr);if(toPresent)vkDestroySemaphore(r.device,toPresent,nullptr);
        result["interrupted"]=bool(state->stop);std::ofstream("activity-result.json")<<result.dump(2)<<"\n";
        std::ofstream("status.txt")<<"complete";
    } catch(const std::exception& e) {std::ofstream("status.txt")<<"ERROR: "<<e.what();__android_log_print(ANDROID_LOG_ERROR,"LocalExposure","%s",e.what());}
    ANativeWindow_release(window);
    ANativeActivity_finish(state->activity);
}
extern "C" __attribute__((visibility("default"))) void ANativeActivity_onCreate(ANativeActivity* activity,void*,size_t) {
    auto* state=new ActivityState;state->activity=activity;activity->instance=state;
    ANativeActivity_setWindowFlags(activity,AWINDOW_FLAG_KEEP_SCREEN_ON|AWINDOW_FLAG_FULLSCREEN,0);
    activity->callbacks->onNativeWindowCreated=[](ANativeActivity* a,ANativeWindow* window) {auto* s=static_cast<ActivityState*>(a->instance);if(!s->worker.joinable()){ANativeWindow_acquire(window);s->worker=std::thread(runActivity,s,window);}};
    activity->callbacks->onNativeWindowDestroyed=[](ANativeActivity* a,ANativeWindow*) {static_cast<ActivityState*>(a->instance)->stop=true;};
    activity->callbacks->onDestroy=[](ANativeActivity* a) {auto* s=static_cast<ActivityState*>(a->instance);s->stop=true;if(s->worker.joinable())s->worker.join();delete s;};
}
