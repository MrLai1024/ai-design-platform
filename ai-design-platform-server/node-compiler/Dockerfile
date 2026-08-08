FROM node:24-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY src/ ./src/

ENV PORT=5199
EXPOSE 5199

CMD ["node", "src/server.js"]
