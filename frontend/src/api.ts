import axios from 'axios';

// Shared axios instance with base URL pointing to the Vite proxy prefix.
// The proxy in vite.config.ts strips "/api" and forwards to the backend.
const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
});

export default api;
