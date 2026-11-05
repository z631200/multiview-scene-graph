
# 載入原本的 Bash 設定
if [ -f "$HOME/.bashrc" ]; then
    source "$HOME/.bashrc"
fi

# 初始化 Conda
source "$HOME/anaconda3/etc/profile.d/conda.sh"

# 自動啟用 multi-view 環境
conda activate multi-view
