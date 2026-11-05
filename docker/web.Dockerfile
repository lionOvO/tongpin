FROM node:22-alpine AS build
WORKDIR /build/frontend
ENV NODE_OPTIONS=--max-old-space-size=768
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
COPY config/ /build/config/
RUN npm run build
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY docker/frontend.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/frontend/dist /usr/share/nginx/html
EXPOSE 8501
