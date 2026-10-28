ARG NODE_IMAGE=node:22-bookworm-slim
FROM ${NODE_IMAGE}

ARG CLAUDE_CODE_VERSION=2.1.311
RUN if command -v apk >/dev/null; then \
      apk add --no-cache git ca-certificates ripgrep; \
    else \
      apt-get update \
      && apt-get install -y --no-install-recommends git ca-certificates ripgrep \
      && rm -rf /var/lib/apt/lists/*; \
    fi \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && mkdir -p /home/node/.claude /workspace \
    && chown -R node:node /home/node/.claude /workspace

COPY entrypoint.cjs /usr/local/lib/dual-claude-entrypoint.cjs
USER node
WORKDIR /workspace
ENV CLAUDE_CONFIG_DIR=/home/node/.claude
ENTRYPOINT ["node", "/usr/local/lib/dual-claude-entrypoint.cjs"]
