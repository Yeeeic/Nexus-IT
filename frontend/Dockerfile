# Multi-stage production Dockerfile for NEXUS IT Frontend
# Stage 1: Build static assets
FROM node:22-alpine AS builder
WORKDIR /app

# Copy dependency definitions and install cleanly
COPY package.json package-lock.json ./
RUN npm ci

# Copy source code and build production bundle
COPY . .
RUN npm run build

# Stage 2: Minimal, secure NGINX runtime
FROM nginx:1.27-alpine AS runtime

# Copy custom security-hardened nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled assets from build stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
