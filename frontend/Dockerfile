FROM node:24-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package files
COPY package.json pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source
COPY . .

# Build
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN pnpm build

# Production image
FROM node:24-alpine

WORKDIR /app

# Copy built output
COPY --from=builder /app/build ./build
COPY --from=builder /app/package.json ./

# Minimal production deps
RUN corepack enable && corepack prepare pnpm@latest --activate

EXPOSE 3000

ENV HOST=0.0.0.0
ENV PORT=3000
ENV ORIGIN=http://localhost:3000

CMD ["node", "build"]
