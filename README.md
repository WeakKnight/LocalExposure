# Local Exposure

基于 **SlangPy + Slang** 的三曝光 Fusion Local Exposure 实验：通过多尺度融合调整局部明暗，再把局部曝光乘回 HDR，最后使用 ACES Filmic 显示。

## 效果对比

同一 HDR、相同全局曝光与 ACES 曲线。左侧仅全局曝光，右侧启用局部曝光；可点击图片查看大图。

| 仅全局曝光 + ACES | Fusion Local Exposure + ACES |
| :---: | :---: |
| ![Sundowner Deck：仅全局曝光](docs/images/sundowner_deck-before.png) | ![Sundowner Deck：局部曝光后](docs/images/sundowner_deck-after.png) |
| ![Veranda：仅全局曝光](docs/images/veranda-before.png) | ![Veranda：局部曝光后](docs/images/veranda-after.png) |

上：露台屋顶和地板的暗部细节；下：门廊天花板和砖墙的亮度变化。

**示例参数**：Highlight / Shadow Contrast Scale 均为 **0.5**（三曝光偏移 ±3 EV），Sigma＝0.2；上图全局曝光 −2 EV，下图 −1 EV。为便于观察，这里使用比程序默认 **0.8** 更强的调整。

## 快速运行

Windows · Python 3.12 · 支持 D3D12 / Vulkan 的 GPU。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

复现上方露台效果：

```powershell
.\run.ps1 --image Assets/sundowner_deck_4k.exr --exposure -2 --highlight-contrast 0.5 --shadow-contrast 0.5 --view compare
```

View 提供 **最终效果 / 原图对比 / 局部曝光 EV**。支持切换素材、调节曝光与权重；**F5** 重载 shader，**F2** 导出 PNG，**Esc** 退出。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--exposure` | 0 | 全局曝光 EV |
| `--highlight-contrast` / `--shadow-contrast` | 0.8 / 0.8 | 各侧曝光偏移幅度为 `6 × (1 − Scale)` EV；1 表示无偏移 |
| `--sigma` | 0.2 | 曝光权重宽度，越小选择越集中 |
| `--levels` | 16 | 金字塔最大层数，按图像短边限制 |

## 实现概览

`HDR → 三曝光感知亮度与权重 → 多尺度金字塔 → 加权 Laplacian 与从粗到细重建 → 局部曝光倍率 → HDR × 曝光 → ACES → sRGB`

亮度与权重生成在 `shaders/pyramid.slang`，融合、重建和曝光反解在 `shaders/fusion.slang`。采用 UE Fusion 风格的四点下采样与 exp2 权重；当前使用 RGB ACES 近似后取亮度，并非 UE FilmToneMap 的完整复刻。

```powershell
.\.venv\Scripts\python.exe test_pyramid.py          # 数值回归测试
.\.venv\Scripts\python.exe docs/render_examples.py  # 重新生成 README 对比图
```

## References

- [Bart Wronski — Exposure Fusion: local tonemapping for real-time rendering](https://bartwronski.com/2022/02/28/exposure-fusion-local-tonemapping-for-real-time-rendering/)：三曝光、多尺度融合及实时渲染中的应用。
- [kbmajeed / exposure_fusion](https://github.com/kbmajeed/exposure_fusion)：Mertens 等人 Exposure Fusion 方法的参考实现，包含权重与金字塔融合。
- **Unreal Engine 源码**：`Engine/Shaders/Private/PostProcessLocalExposure.usf`，用于对照 Fusion 的参数语义和下采样实现（需自行获取引擎源码）。
- [Krzysztof Narkowicz — ACES Filmic Tone Mapping Curve](https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/)：本项目使用的 filmic 曲线近似。
- [SlangPy 文档](https://slangpy.shader-slang.org/en/latest/)：GPU 计算、资源与窗口接口。

示例 HDRI 来自 Poly Haven，采用 CC0：[Sundowner Deck / Dario Barresi](https://polyhaven.com/a/sundowner_deck)、[Veranda / Greg Zaal](https://polyhaven.com/a/veranda)。
