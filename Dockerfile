FROM python:3.11-slim

WORKDIR /app

# Install dependencies (use Tsinghua mirror for faster download)
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Patch agents library to fix TensorFlow compatibility issue
RUN python -c " \
import site; \
import os; \
networks_path = os.path.join(site.getsitepackages()[0], 'agents/scripts/networks.py'); \
if os.path.exists(networks_path): \
    with open(networks_path, 'r') as f: \
        content = f.read(); \
    if 'tfd = tf.contrib.distributions' in content: \
        content = content.replace('tfd = tf.contrib.distributions', 'tfd = None'); \
        with open(networks_path, 'w') as f: \
            f.write(content); \
        print('Patched networks.py'); \
"

# Copy project files
COPY . .

# Create data directory
RUN mkdir -p ./assert

# Environment variables (can be overridden at runtime)
ENV OPENAI_API_KEY=""
ENV OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
ENV OPENAI_MODEL="qwen-max"
ENV OPENAI_VISON_MODEL="qwen-vl"

# Expose ports
EXPOSE 8000 8900 8501

# Start command - run all services in background
CMD python main_server.py & \
    python main_mcp.py & \
    streamlit run demo/streamlit_demo.py --server.port 8501 --server.address 0.0.0.0