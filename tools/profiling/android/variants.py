"""Explicit profiling presets; experimental entries are not runtime defaults.

Default mobile algorithm: guided-vertical2-t256. Frozen control: gather-reduction.
Output integration alternatives:
gather-work16 and gather-fragment. See docs/performance/archive/twohour-optimization.md.
The remaining presets preserve experiments and independent historical controls.
"""

VARIANTS = {
    'lossless': {},
    'compute-control': {'compute_srgb': True, 'unfused_control': True},
    'cached-baseline': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True},
    'log-exposure': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True},
    'tile32x16': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'tile_x': 32, 'tile_y': 16},
    'tile32x32': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'tile_x': 32, 'tile_y': 32},
    'separable': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True},
    'work16': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'work_x': 16, 'work_y': 16},
    'work32x8': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'work_x': 32, 'work_y': 8},
    'load-reduction': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'reduction_load': True},
    'separable32x16': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'tile_x': 32, 'tile_y': 16},
    'shared-reuse': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'reuse_shared': True},
    'single-weight': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True},
    'precomputed-ev': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True},
    'readonly-input': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'readonly_input': True},
    'tail-fusion': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'tail_fusion': True},
    'weight-unorm': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True},
    'curve-log': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'curve_log': True},
    'cooperative-reduction': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'cooperative_reduction': True},
    'combined': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True},
    'half-guide': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'half_guide': True},
    'half-compact': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'half_guide': True, 'half_compact': True},
    'guided8x8': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'tile_x': 8, 'tile_y': 8},
    'guided16x8': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'tile_x': 16, 'tile_y': 8},
    'guided8x16': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'tile_x': 8, 'tile_y': 16},
    'guided32x8': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'tile_x': 32, 'tile_y': 8},
    'residual': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True},
    'residual-packed': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'packed_residual': True},
    'guided32x16pre': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'single_weight': True, 'weight_unorm': True, 'precomputed_ev': True, 'tile_x': 32, 'tile_y': 16},
    'separable-reduction': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'separable_reduction': True},
    'residual-centered': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'packed_residual': True, 'packed_weight_bias': 1/3},
    'residual-scaled': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'residual_scale': 1024.0},
    'residual-centered-scaled': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'packed_residual': True, 'packed_weight_bias': 1/3, 'residual_scale': 1024.0},
    'residual-float': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'residual_float': True},
    'moment-pass': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'moment_input': True},
    'log-product': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'log_product': True},
    'gather-reduction': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True},
    'scalar-reduction': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'scalar_reduction': True, 'log_product': True},
    'gather-half': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'half_gather': True},
    'gather-moment': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'moment_input': True},
    'joint-upsample': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'joint_upsample': True},
    'gather-snorm': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'packed_residual': True, 'packed_snorm': True},
    'gather-halfproducts': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'half_moment_products': True},
    'gather-reuse': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'reuse_shared': True},
    'gather-pad': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'shared_padding': 1},
    'gather-reuse-pad': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'reuse_shared': True, 'shared_padding': 1},
    'gather-work16': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'work_x': 16, 'work_y': 16},
    'gather-fragment': {'half_aux': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True},
    'gather-fullcoeff': {'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True},
    'gather-floatresidual': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'residual_float': True},
    'gather16x4': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'gather_x': 16, 'gather_y': 4},
    'gather16x8': {'half_aux': True, 'compute_srgb': True, 'cached_baseline': True, 'log_exposure': True, 'separable_guided': True, 'precomputed_ev': True, 'residual_pyramid': True, 'gather_reduction': True, 'gather_x': 16, 'gather_y': 8},
    'half-aux-compute': {'half_aux': True, 'compute_srgb': True},
    'half-aux': {'half_aux': True},
    'reduction4': {'reduction_grid': 2},
    'radius1': {'guided_radius': 1},
    'mobile': {'half_aux': True, 'reduction_grid': 2, 'guided_radius': 1},
}

# Research only: image gate passed, but foreground timing regressed.
# See docs/performance/archive/experiments/wave-operations.md; not a retained optimization.
VARIANTS["wave-reduction"] = {**VARIANTS["gather-reduction"], "cooperative_reduction": True, "wave_reduction": True}

# Short-window register reuse: batch2 has modest phone gains and remains opt-in.
# Batch4/sliding4 did not improve the chain. See guided-window-reuse.md.
for batch in (2,4):
    VARIANTS[f"guided-batch{batch}"] = {**VARIANTS["gather-reduction"], "guided_batch": batch}
VARIANTS["guided-sliding4"] = {**VARIANTS["guided-batch4"], "guided_sliding": True}

# Vertical reuse: 256 threads is retained; 128 is a rejected experiment.
# Same 16x16 output tile. See guided-vertical-reuse.md.
for threads_y in (16,8):
    VARIANTS[f"guided-vertical2-t{threads_y*16}"] = {**VARIANTS["gather-reduction"], "guided_vertical": 2, "guided_threads_y": threads_y}

DEFAULT_VARIANT = "guided-vertical2-t256"
