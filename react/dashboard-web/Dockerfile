# Dashboard.Web - React + Vite front-end
# Two-stage build: node for compiling, nginx for serving.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
# Use China npm mirror for speed. Override with --build-arg for non-China.
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry ${NPM_REGISTRY} && \
    npm install --no-audit --no-fund
COPY . .
# Build outputs to /app/dist. Vite reads vite.config.ts for proxy only in dev.
RUN npm run build

FROM nginx:1.27-alpine AS serve
# Single-page app: any unknown route falls back to index.html so the
# React Router can pick it up.
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  location /api/ { proxy_pass http://dashboard-service:8080; }\n\
  location / { try_files $uri /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
