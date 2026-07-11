# Use official Node.js LTS image
FROM node:20-slim

# Install dependencies (ensure sharp or other native modules build correctly)
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN npm install --production

# Copy the rest of the application
COPY . .

# Expose the production port
EXPOSE 3002

# Start the Matrix
CMD ["node", "pure-backend.js"]