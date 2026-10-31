FROM node:20.17-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE=http://localhost:8080/api/v1
ARG VITE_VOICE_BASE=http://localhost:7861
ARG VITE_SIMULATOR_BASE=http://localhost:8090/v1
ARG VITE_MOCK=0
ENV VITE_API_BASE=$VITE_API_BASE VITE_VOICE_BASE=$VITE_VOICE_BASE \
    VITE_SIMULATOR_BASE=$VITE_SIMULATOR_BASE VITE_MOCK=$VITE_MOCK
RUN npm run build

# Runs as the image's non-root nginx user, so it listens on 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
