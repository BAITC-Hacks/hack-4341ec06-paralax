import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import Stage8Dashboard from './Stage8Dashboard';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{window.location.pathname.startsWith('/demo') ? <App /> : <Stage8Dashboard />}</React.StrictMode>,
);
