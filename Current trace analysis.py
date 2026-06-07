import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
import os

# =========================
# Data load
# =========================
def load_current_data(folder_path, file_name):
    full_path = os.path.join(folder_path, file_name)
    df = pd.read_excel(full_path, sheet_name='Sheet1')
    df = df[['Timestamps (sec)', 'Current (A)']].dropna()
    df.set_index('Timestamps (sec)', inplace=True)
    return df['Current (A)']

# =========================
# Get Mode
# =========================
def safe_mode(data):
    try:
        mode_result = stats.mode(data, nan_policy='omit', keepdims=False).mode
        return float(mode_result[0]) if isinstance(mode_result, np.ndarray) else float(mode_result)
    except Exception as e:
        print("⚠️ Mode :", e)
        return np.nan

# =========================
# Get Threshold
# =========================
def auto_detect_threshold(current_data, bins=100):
    counts, bin_edges = np.histogram(current_data, bins=bins)
    peak_indices = counts.argsort()[-2:]
    peak_bins = np.sort([bin_edges[peak_indices[0]], bin_edges[peak_indices[1]]])
    return np.mean(peak_bins)

# =========================
# Get Transition
# =========================
def detect_on_to_off_transitions_normalized_only(current_series, on_mode, off_mode,
                                                  norm_thresh=0.3, min_gap=5):
    norm = (current_series - off_mode) / (on_mode - off_mode)
    norm = norm.clip(0, 1)
    condition = norm <= norm_thresh

    transitions = []
    prev_time = -np.inf
    for t, is_transition in condition.items():
        if is_transition and (t - prev_time) > min_gap:
            transitions.append(t)
            prev_time = t
    return transitions

# =========================
# Visualization
# =========================
def plot_with_mode_baselines(current_data, threshold, norm_thresh=0.3, min_gap=5):
    on_data = current_data[current_data > threshold]
    off_data = current_data[current_data <= threshold]
    on_mode = safe_mode(on_data)
    off_mode = safe_mode(off_data)

    transitions = detect_on_to_off_transitions_normalized_only(
        current_series=current_data,
        on_mode=on_mode,
        off_mode=off_mode,
        norm_thresh=norm_thresh,
        min_gap=min_gap
    )

    off_threshold_current = off_mode + (on_mode - off_mode) * norm_thresh
    plt.figure(figsize=(12, 6))
    plt.plot(current_data.index, current_data.values, label='Current', color='gray')
    plt.axhline(on_mode, color='blue', linestyle='--', label=f'ON Mode: {on_mode:.2e}')
    plt.axhline(off_mode, color='green', linestyle='--', label=f'OFF Mode: {off_mode:.2e}')
    plt.axhline(off_threshold_current, color='orange', linestyle='--', label=f'Norm Thresh ({norm_thresh:.2f})')

    for i, t in enumerate(transitions):
        plt.plot(t, current_data.loc[t], 'ro', label='OFF Transition' if i == 0 else "")

    plt.title("Current with ON/OFF Baselines (Normalized Threshold Only)")
    plt.xlabel("Time (s)")
    plt.ylabel("Current (A)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    print("\n ON → OFF :")
    for t in transitions:
        print(f"  {t:.4f}")

    
    if transitions:
        num, cols = len(transitions), 2
        rows = (num + 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(12, 3 * rows), sharex=False)
        axes = axes.flatten()
        for i, t in enumerate(transitions):
            ax = axes[i]
            sliced = current_data[(current_data.index >= t - 5) & (current_data.index <= t + 5)]
            ax.plot(sliced.index, sliced.values, color='gray')
            ax.axhline(off_mode, color='green', linestyle='--', label='OFF Mode')
            ax.axhline(off_threshold_current, color='orange', linestyle='--', label=f'Norm Thresh ({norm_thresh:.2f})')
            ax.axhline(on_mode, color='blue', linestyle='--', label='ON Mode')
            ax.axvline(t, color='red', linestyle='--', label='OFF Transition')
            ax.set_title(f"OFF Transition @ {t:.4f}s")
            ax.set_ylabel("Current (A)")
            ax.legend()
            ax.grid(True)
        for j in range(i + 1, len(axes)):
            fig.delaxes(axes[j])
        plt.tight_layout()
        plt.show()

# =========================
# Histogram
# =========================
def calculate_stats(current_data, threshold):
    on_data = current_data[current_data > threshold]
    off_data = current_data[current_data <= threshold]
    stats_dict = {
        "ON": {"Mean": on_data.mean(), "Median": on_data.median(), "Mode": safe_mode(on_data)},
        "OFF": {"Mean": off_data.mean(), "Median": off_data.median(), "Mode": safe_mode(off_data)},
    }

    fig, axs = plt.subplots(1, 2, figsize=(12, 6))
    for idx, (label, data, color) in enumerate(zip(["OFF", "ON"], [off_data, on_data], ["green", "blue"])):
        mean, median, mode, std = stats_dict[label]["Mean"], stats_dict[label]["Median"], stats_dict[label]["Mode"], data.std()
        x_min = min(mean, median, mode) - max(abs(mean), std) * 0.5
        x_max = max(mean, median, mode) + max(abs(mean), std) * 0.5
        axs[idx].hist(data, bins=30, color=color, edgecolor='black')
        axs[idx].axvline(mean, color='black', linestyle='-', label=f'Mean: {mean:.2e}')
        axs[idx].axvline(median, color='black', linestyle='--', label=f'Median: {median:.2e}')
        axs[idx].axvline(mode, color='black', linestyle=':', label=f'Mode: {mode:.2e}')
        axs[idx].set_title(f"{label} Current Distribution")
        axs[idx].set_xlim(x_min, x_max)
        axs[idx].set_ylabel("Frequency")
        axs[idx].legend()
        axs[idx].grid(True)
    axs[1].set_xlabel("Current (A)")
    plt.tight_layout()
    plt.show()

    for state in stats_dict:
        print(f"\n--- {state}  ---")
        for key, value in stats_dict[state].items():
            print(f"{key:<7}: {value:.2e}")

# =========================
# Main
# =========================
if __name__ == "__main__":
    folder = r"XX" # Replace with your folder path
    filename = "XX.xlsx" # Replace with your file name
    
    current_data = load_current_data(folder, filename)

    
    plt.figure(figsize=(10, 6))
    plt.hist(current_data, bins=50, color='skyblue', edgecolor='black')
    plt.title("Histogram of Current (A)")
    plt.xlabel("Current (A)")
    plt.ylabel("Frequency")
    plt.grid(True)
    plt.tight_layout()
    plt.show()

    threshold = auto_detect_threshold(current_data)
    on_data = current_data[current_data > threshold]
    off_data = current_data[current_data <= threshold]
    on_mode = safe_mode(on_data)
    off_mode = safe_mode(off_data)
    norm_thresh = 0.3

    off_thresh_current = off_mode + (on_mode - off_mode) * norm_thresh

    
    print(f"\ Threshold          : {threshold:.4e}")
    print(f" ON Mode (Baseline)            : {on_mode:.4e}")
    print(f" OFF Mode (Baseline)           : {off_mode:.4e}")
    print(f" Norm OFF Threshold Current    : {off_thresh_current:.4e} (norm_thresh={norm_thresh})")

    
    calculate_stats(current_data, threshold)
    plot_with_mode_baselines(
        current_data,
        threshold,
        norm_thresh=norm_thresh,
        min_gap=100
    )
