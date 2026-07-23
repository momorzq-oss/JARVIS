# JARVIS GUI Performance Report

Date: 2026-07-20

## Native Source Measurements

- Process start to visible window, including imports: 4.483 seconds.
- Warm GUI construction to visible window: 3.120 seconds.
- Normalized idle CPU after capability scan and three-second settling period: 1.071%.
- Resident memory after capability scan: 201.5 MiB.
- Native maximized logical size: 1280 × 649 at the active Windows scale.
- Native window capture: 1920 × 974 physical pixels.
- Capability registry loaded: 163 total, 142 working, 21 requiring login.

Evidence:

- `.test_tmp/cinematic_gui_performance.json`
- `.test_tmp/cinematic_gui_performance_optimized.json`
- `.test_tmp/cinematic_gui_validated.png`

## Performance Controls

- AI core: 30 FPS only during active states; 4 FPS during ready/idle; 2 FPS in reduced motion.
- Waveforms: timers stop completely at zero input and restart only for real input/speech levels.
- Status and session snapshots: low-frequency 1.5 second polling plus event signals.
- Capability discovery: background worker only.
- Typed commands: one persistent worker thread to preserve Playwright affinity.
- Desktop preview: no continuous capture.

## Scaled Layout Result

The three dashboard columns remain accessible at the active 1080p-class scaled desktop. Vertical overflow uses per-column scroll areas, preventing panel overlap. The center AI core no longer overlaps execution-summary panels at 150% Windows scaling.

## 2026-07-23 Activation Geometry Regression

The single-instance shortcut activation path previously called `showNormal()`. On the 150%-scaled primary display, that restored the designed 1680x940 logical size as a 2520-pixel physical window spanning both monitors. The activation path now preserves the maximized mode used at startup. Live validation showed a screen-bounded `(0, 34)-(1920, 1007)` window before and after a second Desktop-shortcut activation, exactly one JARVIS process, and a responsive painted client area. The supported Python 3.12 suite reports 592 collected, 592 passed, 0 failed, and 0 skipped.
