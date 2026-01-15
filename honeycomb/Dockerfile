# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Build argument for API URL (Vite needs this at build time)
ARG VITE_API_URL=http://localhost:4000
ENV VITE_API_URL=$VITE_API_URL

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine AS production

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port
EXPOSE 3000

# Override the default entrypoint to skip noisy scripts
ENTRYPOINT []
CMD ["sh", "-c", "echo '[Hive] Frontend ready at http://localhost:3000' && exec nginx -g 'daemon off;' 2>/dev/null"]
