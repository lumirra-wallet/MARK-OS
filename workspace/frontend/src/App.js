import React, { useEffect, useState } from 'react';
import './styles.css';

// Pro landing page animation and image fetching
function LandingPage() {
  const [images, setImages] = useState([]);

  useEffect(() => {
    fetch('https://api.unsplash.com/photos/random?count=3&client_id=YOUR_UNSPLASH_ACCESS_KEY')
      .then((res) => res.json())
      .then((data) => {
        setImages(Array.isArray(data) ? data.map(img => img.urls.regular) : []);
      });
  }, []);

  return (
    <div className="landing fade-in">
      <h1 className="animated-title">Welcome to the Pro Site</h1>
      <div className="images">
        {images.map((src, idx) => (
          <img key={idx} src={src} alt="Unsplash example" className="slide-up" />
        ))}
      </div>
      <a href="#login" className="animated-btn">Login</a>
    </div>
  );
}

function LoginPage() {
  return (
    <div className="login-container fade-in">
      <h2 className="slide-up">Login</h2>
      <form className="login-form">
        <input type="text" placeholder="Username" className="animated-input"/>
        <input type="password" placeholder="Password" className="animated-input"/>
        <button className="animated-btn">Login</button>
      </form>
    </div>
  );
}

function App() {
  const [page, setPage] = useState('landing');

  useEffect(() => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'login') setPage('login');
    else setPage('landing');
    window.onhashchange = () => {
      const newHash = window.location.hash.replace('#', '');
      setPage(newHash === 'login' ? 'login' : 'landing');
    };
  }, []);

  return (
    <div>
      {page === 'landing' ? <LandingPage /> : <LoginPage />}
    </div>
  );
}

export default App;
