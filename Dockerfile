# ============================================
#  AI Toolkit - 金呈的工具集
#  包含: jinchen / interface-notes / jinchen_fd_kit
# ============================================

FROM python:3.11-slim

LABEL maintainer="jincheng3870682453@gmail.com"
LABEL description="AI Toolkit: jinchen + interface-notes + fd-kit"

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NUWA_ENV=dev

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─── 安装 Python 依赖 ───────────────────────
COPY interface-notes/requirements.txt /tmp/if-req.txt
COPY jinchen_final/jinchen_v3/requirements.txt /tmp/jc-req.txt
RUN pip install --no-cache-dir -r /tmp/if-req.txt -r /tmp/jc-req.txt \
    && rm /tmp/*.txt

# ─── 复制三个项目 ───────────────────────────
COPY jinchen_final/jinchen_v3/ ./jinchen/
COPY interface-notes/ ./interface-notes/
COPY jinchen_fd_kit/ ./jinchen_fd_kit/

# ─── 统一启动脚本 ───────────────────────────
RUN cat > /usr/local/bin/aitoolkit << 'EOF'
#!/bin/bash
clear
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        🛡️  AI Toolkit 启动器            ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  [1] 🔥 jinchen (Word体系 - AI行为治理)"
echo "  [2] 📝 interface-notes (AI接口文档)"
echo "  [3] 🗣️  jinchen_fd_kit (全双工对话)"
echo "  [q] 退出"
echo ""
read -p "  👉 选择: " choice
echo ""
case $choice in
  1)
    echo "  → jinchen 就绪"
    echo "    验证:  python3 verify.py"
    echo "    演示:  python3 examples/04_token_saving.py"
    echo "    网关:  python3 Toolkit/gateway.py"
    cd /app/jinchen && bash
    ;;
  2)
    echo "  → interface-notes 就绪"
    echo "    扫描: python -m interface_notes --help"
    cd /app/interface-notes && bash
    ;;
  3)
    echo "  → jinchen_fd_kit 就绪"
    echo "    演示: python3 jinchen_fd_demo.py"
    cd /app/jinchen_fd_kit && bash
    ;;
  q|Q) exit 0 ;;
  *) echo "  无效选择" ;;
esac
EOF
chmod +x /usr/local/bin/aitoolkit

# 默认入口
CMD ["aitoolkit"]