"""Whole-command GPU duration: RHI queries or native Metal command-buffer time."""
import ctypes
import math
import sys

import slangpy as spy


class GpuTimer:
    def __init__(self, device):
        self.device = device
        if device.has_feature(spy.Feature.timestamp_query):
            self.kind = 'RHI timestamp queries, whole submission'
            self.pool = device.create_query_pool(spy.QueryType.timestamp, 2)
            self.metal = False
        elif device.info.type == spy.DeviceType.metal and sys.platform == 'darwin':
            # SlangPy's Metal RHI does not expose timestamp queries. The native
            # callback supplies the actual command buffer, not a CPU stopwatch.
            self.kind = 'Metal MTLCommandBuffer GPUStartTime/GPUEndTime'
            self.metal = True
            self.objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
            self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
            self.objc.sel_registerName.restype = ctypes.c_void_p
            self.objc.objc_retain.argtypes = [ctypes.c_void_p]
            self.objc.objc_retain.restype = ctypes.c_void_p
            self.objc.objc_release.argtypes = [ctypes.c_void_p]
            self.send_double = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', self.objc))
            self.start_selector = self.objc.sel_registerName(b'GPUStartTime')
            self.end_selector = self.objc.sel_registerName(b'GPUEndTime')
        else:
            raise RuntimeError('No verified GPU timing mechanism for this backend; CPU time is not a substitute')

    def measure(self, record):
        encoder = self.device.create_command_encoder()
        handles = []
        if not self.metal:
            self.pool.reset()
            encoder.write_timestamp(self.pool, 0)
        record(encoder)
        if self.metal:
            def retain(handle):
                if handle.type != spy.NativeHandleType.MTLCommandBuffer or not handle.value:
                    raise RuntimeError('Expected a native Metal command buffer')
                handles.append(self.objc.objc_retain(handle.value))
            encoder.execute_callback(retain)
        else:
            encoder.write_timestamp(self.pool, 1)
        command_buffer = encoder.finish()
        try:
            self.device.submit_command_buffer(command_buffer)
            self.device.wait()
            if self.metal:
                if len(handles) != 1:
                    raise RuntimeError('Missing Metal command buffer timing handle')
                start = self.send_double(handles[0], self.start_selector)
                end = self.send_double(handles[0], self.end_selector)
            else:
                start, end = self.pool.get_timestamp_results(0, 2)
            duration = (end - start) * 1000
            if not (math.isfinite(start) and math.isfinite(end) and end > start and start > 0):
                raise RuntimeError(f'Invalid GPU timestamps: {start}, {end}')
            return duration
        finally:
            for handle in handles:
                self.objc.objc_release(handle)
