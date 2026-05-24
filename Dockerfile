# AntiBlack Application Dockerfile
# Multi-stage build for optimized production image

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============================================
# Stage 2: Production
# ============================================
FROM python:3.11-slim AS production

# Security: Run as non-root user
RUN groupadd -r antiblack && useradd -r -g antiblack antiblack

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /home/antiblack/.local

# Copy application code
COPY --chown=antiblack:antiblack . .

# Create necessary directories
RUN mkdir -p /app/logs /app/rag_storage && \
    chown -R antiblack:antiblack /app/logs /app/rag_storage

# Switch to non-root user
USER antiblack

# Environment setup
ENV PATH=/home/antiblack/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/system/ready || exit 1

# Run the application
CMD ["python", "main.py"]