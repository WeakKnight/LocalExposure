"""Production graph and independent benchmark controls.

Shader algorithms are fixed in shaders/compact/. These values describe resource
formats, dispatch geometry and graph scheduling for the host.
"""

PRODUCTION = {'half_aux': True,
 'compute_srgb': True,
 'cached_baseline': True,
 'log_exposure': True,
 'separable_guided': True,
 'precomputed_ev': True,
 'residual_pyramid': True,
 'gather_reduction': True,
 'guided_vertical': 2,
 'guided_threads_y': 16,
 'guided_static_windows': True,
 'guided_batch': 2,
 'guided_direct_moments': True,
 'direct_batch': 1,
 'tail_fusion': True,
 'tail_max_width': 16,
 'tail_max_height': 8,
 'tail_x': 16,
 'fused_fine_reconstruction': True,
 'half_guide': True,
 'half_compact': True,
 'half_row_coefficients': True,
 'reuse_moment_storage': True,
 'guided_gather_rows': True,
 'direct_residual_weights': True,
 'gather_x': 4,
 'gather_y': 8,
 'residual_float_from': 3,
 'compact_tail_storage': True,
 'tail_grid_walk': True,
 'skip_tail_clear': True,
 'fuse_tail_base': True,
 'curve_log': True,
 'gather_quad_log': True,
 'guided_interior_fit': True,
 'shared_input_log': True,
 'pyramid_x': 4,
 'pyramid_y': 16,
 'gather_unsigned_source': True,
 'coefficient_padding': 4,
 'packed_half_coefficients': True}

VARIANTS = {
    "guided-packed-coefficients": dict(PRODUCTION),
    "guided-coefficient-layout": {**PRODUCTION, "packed_half_coefficients": False},
    "lossless": {},
}
DEFAULT_VARIANT = "guided-packed-coefficients"
COMPACT_MODULES = {
    "reduce_setup": "compact/initialize",
    "reduce_setup_gather": "compact/initialize",
    "downsample_compact": "compact/pyramid",
    "tail_reconstruct": "compact/tail",
    "reconstruct_compact": "compact/reconstruct",
    "reconstruct_ev": "compact/reconstruct",
    "reconstruct_ev_fused": "compact/reconstruct",
    "reconstruct_guided": "compact/guided",
}
