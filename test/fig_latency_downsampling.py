import matplotlib.pyplot as plt
import numpy as np

# IEEE 标准字体与样式
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
plt.rcParams['axes.edgecolor'] = '#333333'
plt.rcParams['axes.linewidth'] = 0.8

fig = plt.figure(figsize=(9, 7.2), dpi=300)
gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1], hspace=0.38, wspace=0.28)

cases = ['KiTS-53', 'KiTS-389', 'KiTS-738', 'KiTS-987', 'KiTS-1059']
slices = np.array([53, 389, 738, 987, 1059])
t_pre = np.array([2.2, 2.4, 2.4, 2.6, 2.8])
t_infer = np.array([77.6, 152.3, 254.1, 294.8, 348.2])
t_wall_s = np.array([80, 155, 256, 297, 351]) # 与真实 JSON 墙钟时间一致
t_wall_m = np.array([1.3, 2.6, 4.3, 5.0, 5.8])
d_factor = np.array([1.000, 1.000, 0.542, 0.405, 0.378])
total_organs = np.array([1, 18, 16, 17, 20])
warnings_cnt = np.array([1, 3, 3, 2, 2])

x = np.arange(len(cases))

# =============================================================================
# (a) 耗时堆叠图
# =============================================================================
ax_a = fig.add_subplot(gs[0, :])
c_pre = '#8DA0CB'
c_infer = '#2B5C8F'

p1 = ax_a.bar(x, t_pre, width=0.42, label='Pre-processing ($T_{prep}$)', color=c_pre, edgecolor='#222222', linewidth=0.6)
p2 = ax_a.bar(x, t_infer, width=0.42, bottom=t_pre, label='Model Inference ($T_{infer}$)', color=c_infer, edgecolor='#222222', linewidth=0.6)

ax_a.set_ylabel('Execution Latency (s)', fontsize=9.5, fontweight='bold', color='#222222')
ax_a.set_title('(a) End-to-End Execution Latency Decomposition Across Benchmark Cohort', fontsize=10.5, fontweight='bold', loc='left', pad=8)
ax_a.set_xticks(x)
ax_a.set_xticklabels([f'{c}\n({s} Slices)' for c, s in zip(cases, slices)], fontsize=8.5)
ax_a.grid(True, linestyle='--', alpha=0.35, axis='y')
ax_a.set_ylim(0, 420)

for i, (total_s, total_m) in enumerate(zip(t_wall_s, t_wall_m)):
    ax_a.text(i, total_s + 10, f'{total_m:.1f} min\n({total_s}s)', ha='center', va='bottom', fontsize=8, fontweight='bold', color='#1A2530')

ax_a.legend(loc='upper left', frameon=True, facecolor='#FFFFFF', edgecolor='#E0E0E0', framealpha=0.95, fontsize=8.5)

# =============================================================================
# (b) 降采样 Profile (优化了触发虚线和文字排版)
# =============================================================================
ax_b = fig.add_subplot(gs[1, 0])
c_line = '#C0392B'

ax_b.plot(x, d_factor, marker='o', color=c_line, linewidth=2.0, markersize=6, label='Downsample Ratio ($d$)')
ax_b.axhline(y=1.0, color='#95A5A6', linestyle='--', alpha=0.7, linewidth=1.0)
ax_b.axvline(x=1.6, color='#555555', linestyle=':', linewidth=1.2) # 调整虚线位置

ax_b.text(1.65, 0.58, 'Adaptive Triggered\n($N > 400$ Slices)', fontsize=7.8, color='#444444', fontstyle='italic', fontweight='bold')
ax_b.set_ylabel('Z-Axis Scaling Factor ($d$)', fontsize=9.5, fontweight='bold', color='#222222')
ax_b.set_title('(b) Dynamic Downsampling Profile', fontsize=10, fontweight='bold', loc='left', pad=8)
ax_b.set_xticks(x)
ax_b.set_xticklabels(cases, fontsize=8, rotation=15)
ax_b.set_ylim(0.2, 1.15)
ax_b.grid(True, linestyle='--', alpha=0.35)

for i, txt in enumerate(d_factor):
    offset = (0, 7) if i != 2 else (0, -14) # 避免 KiTS-738 文字遮挡折线
    ax_b.annotate(f'{txt:.3f}', (x[i], d_factor[i]), textcoords="offset points", xytext=offset, ha='center', fontsize=7.5, fontweight='bold', color='#222222')

# =============================================================================
# (c) 器官与 Warning (优化柱体间距与 X 轴)
# =============================================================================
ax_c = fig.add_subplot(gs[1, 1])
c_organ = '#34495E'
c_warn = '#E74C3C'

bars = ax_c.bar(x - 0.1, total_organs, width=0.35, color=c_organ, alpha=0.9, label='Extracted Organs', edgecolor='#2C3E50', linewidth=0.5)
ax_c.set_ylabel('Extracted Anatomical Classes', color=c_organ, fontsize=9.5, fontweight='bold')
ax_c.tick_params(axis='y', labelcolor=c_organ)
ax_c.set_ylim(0, 25)

ax_c2 = ax_c.twinx()
lines = ax_c2.plot(x + 0.1, warnings_cnt, color=c_warn, marker='s', linewidth=1.8, linestyle='-', markersize=5.5, label='Clinical Warnings')
ax_c2.set_ylabel('Flagged Clinical Warnings', color=c_warn, fontsize=9.5, fontweight='bold')
ax_c2.tick_params(axis='y', labelcolor=c_warn)
ax_c2.set_ylim(0, 5)

ax_c.set_title('(c) Multi-Organ & Anomaly Yield', fontsize=10, fontweight='bold', loc='left', pad=8)
ax_c.set_xticks(x)
ax_c.set_xticklabels(cases, fontsize=8, rotation=15)
ax_c.grid(True, linestyle='--', alpha=0.35, axis='y')

plt.tight_layout()
plt.savefig('fig_composite_performance_dashboard_v2.png', dpi=300, bbox_inches='tight')
print("最终高清微调版已保存：fig_composite_performance_dashboard_v2.png")