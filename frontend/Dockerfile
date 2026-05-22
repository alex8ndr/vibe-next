FROM node:24-alpine AS builder

WORKDIR /app

ARG PNPM_VERSION=11.2.2

# Install pnpm
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate

# Copy package files
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

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

ARG PNPM_VERSION=11.2.2

# Copy built output
COPY --from=builder /app/build ./build
COPY --from=builder /app/package.json ./
COPY --from=builder /app/pnpm-lock.yaml ./
COPY --from=builder /app/pnpm-workspace.yaml ./

# Minimal production deps
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate
RUN pnpm install --frozen-lockfile --prod

EXPOSE 3000

ENV HOST=0.0.0.0
ENV PORT=3000
ARG ORIGIN=http://localhost:3000
ENV ORIGIN=$ORIGIN

CMD ["node", "build"]
