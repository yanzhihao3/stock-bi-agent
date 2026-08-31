FROM python:3.11-slim

WORKDIR /app

# Install dependencies (use Tsinghua mirror for faster download)
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Copy project files
COPY . .

# Create data directory
RUN mkdir -p ./assert

# Environment variables (can be overridden at runtime)
ENV OPENAI_API_KEY=""
ENV OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
ENV OPENAI_MODEL="qwen-max"
ENV OPENAI_VISON_MODEL="qwen-vl"
ENV JWT_SECRET="change_me_to_a_long_random_secret_at_least_32_bytes"
ENV JWT_EXPIRE_MINUTES=1440

# Expose ports
EXPOSE 8000 8900 8501

# Start command - run all services in background
CMD python main_server.py & \
    python main_mcp.py & \
    streamlit run demo/streamlit_demo.py --server.port 8501 --server.address 0.0.0.0
