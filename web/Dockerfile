FROM node:20.17-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_API_BASE=http://localhost:8080/api/v1
ARG VITE_MOCK=0
ENV VITE_API_BASE=$VITE_API_BASE VITE_MOCK=$VITE_MOCK
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
