import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import ReportPage from './reporting/ReportPage';
import './styles.css';

const reportMatch = window.location.pathname.match(/^\/reports\/(report_[a-f0-9]+)\/?$/);

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><>{reportMatch ? <ReportPage reportId={reportMatch[1]} /> : <App />}</></React.StrictMode>);
