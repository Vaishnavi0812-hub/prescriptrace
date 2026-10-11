FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY . .

EXPOSE 5173
# Builds the app and serves it; /api is forwarded to the backend (vite.config.ts).
CMD ["npm", "run", "serve"]
