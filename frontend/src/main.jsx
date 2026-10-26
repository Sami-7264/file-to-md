import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { HistoryProvider } from './context/HistoryContext.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HistoryProvider>
      <App />
    </HistoryProvider>
  </React.StrictMode>,
)
