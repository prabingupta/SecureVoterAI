
(function () {
  'use strict';

  
  if (typeof AOS !== 'undefined') {
    AOS.init({
      duration: 820,
      once:     true,
      offset:   55,
      easing:   'ease-out-cubic',
    });
  }


  /* 
      NAVBAR — scroll shadow + mobile toggle
     */
  (function initNavbar() {
    const navbar    = document.getElementById('navbar');
    const navToggle = document.getElementById('navToggle');
    const mainNav   = document.getElementById('mainNav');
    if (!navbar) return;

    /* Scroll shadow */
    function onScroll() {
      navbar.classList.toggle('navbar-scrolled', window.scrollY > 40);
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if (!navToggle || !mainNav) return;

   
    function openNav() {
      mainNav.classList.add('nav-open');
      navToggle.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
      animateHamburger(true);
    }
    function closeNav() {
      mainNav.classList.remove('nav-open');
      navToggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
      animateHamburger(false);
    }
    function isOpen() { return mainNav.classList.contains('nav-open'); }

    function animateHamburger(open) {
      const spans = navToggle.querySelectorAll('span');
      spans.forEach((s, i) => {
        s.style.transform = open
          ? ['rotate(45deg) translate(5px,5px)', 'scaleX(0)', 'rotate(-45deg) translate(5px,-5px)'][i]
          : '';
        s.style.opacity = (open && i === 1) ? '0' : '1';
      });
    }

    navToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      isOpen() ? closeNav() : openNav();
    });

    /* Close on link click */
    mainNav.querySelectorAll('a').forEach((a) => {
      a.addEventListener('click', () => { if (isOpen()) closeNav(); });
    });

    /* Close on outside click */
    document.addEventListener('click', (e) => {
      if (isOpen() && !mainNav.contains(e.target) && !navToggle.contains(e.target)) closeNav();
    });

    /* Close on Escape */
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen()) closeNav();
    });

    
    window.matchMedia('(min-width: 769px)').addEventListener('change', (e) => {
      if (e.matches && isOpen()) closeNav();
    });
  })();


  /* 
     HERO SLIDER
     */
  (function initSlider() {
    const slides = document.querySelectorAll('.hero-slider .slide');
    const dots   = document.querySelectorAll('.slider-dots .dot');
    const prevBtn = document.getElementById('heroPrev');
    const nextBtn = document.getElementById('heroNext');
    if (!slides.length) return;

    let current = 0;
    let timer   = null;
    const DELAY = 5500;

    function goTo(n) {
      slides[current].classList.remove('active');
      dots[current] && dots[current].classList.remove('active');
      current = (n + slides.length) % slides.length;
      slides[current].classList.add('active');
      dots[current] && dots[current].classList.add('active');
      resetTimer();
    }

    function resetTimer() {
      clearInterval(timer);
      timer = setInterval(() => goTo(current + 1), DELAY);
    }

    prevBtn && prevBtn.addEventListener('click', () => goTo(current - 1));
    nextBtn && nextBtn.addEventListener('click', () => goTo(current + 1));
    dots.forEach((d) => d.addEventListener('click', () => goTo(+d.dataset.slide)));

    /* Keyboard */
    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft')  goTo(current - 1);
      if (e.key === 'ArrowRight') goTo(current + 1);
    });

    /* Touch swipe */
    let touchStartX = 0;
    const heroEl = document.getElementById('home');
    if (heroEl) {
      heroEl.addEventListener('touchstart', (e) => {
        touchStartX = e.changedTouches[0].screenX;
      }, { passive: true });
      heroEl.addEventListener('touchend', (e) => {
        const diff = touchStartX - e.changedTouches[0].screenX;
        if (Math.abs(diff) > 50) diff > 0 ? goTo(current + 1) : goTo(current - 1);
      }, { passive: true });
    }

    resetTimer();
  })();


  
  (function initTypewriter() {
    const el     = document.getElementById('typewriterText');
    const cursor = document.querySelector('.typewriter-cursor');
    if (!el) return;

    const phrases = [
      'Your Vote. Verified.',
      'Secured. Counted Fairly.',
      'Biometric. Encrypted.',
      'Transparent. Trustworthy.',
    ];

    let phraseIdx = 0;
    let charIdx   = 0;
    let deleting  = false;

    function tick() {
      const phrase = phrases[phraseIdx];
      if (!deleting) {
        el.textContent = phrase.slice(0, ++charIdx);
        if (charIdx === phrase.length) {
          deleting = true;
          setTimeout(tick, 1800);
          return;
        }
        setTimeout(tick, 68);
      } else {
        el.textContent = phrase.slice(0, --charIdx);
        if (charIdx === 0) {
          deleting  = false;
          phraseIdx = (phraseIdx + 1) % phrases.length;
          setTimeout(tick, 350);
          return;
        }
        setTimeout(tick, 32);
      }
    }
    tick();
  })();


  /* 
      STAT COUNTERS 
      */
  (function initCounters() {
    function easeOutQuart(t) { return 1 - Math.pow(1 - t, 4); }

    function animateEl(el, target, duration) {
      const start = performance.now();
      (function step(now) {
        const p   = Math.min((now - start) / duration, 1);
        el.textContent = Math.floor(easeOutQuart(p) * target).toLocaleString();
        if (p < 1) requestAnimationFrame(step);
        else el.textContent = target.toLocaleString();
      })(start);
    }

    function observeAndAnimate(selector, attr, duration) {
      const els = document.querySelectorAll(selector);
      if (!els.length) return;
      if (!('IntersectionObserver' in window)) {
        els.forEach((el) => animateEl(el, +el.getAttribute(attr), duration));
        return;
      }
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            animateEl(e.target, +e.target.getAttribute(attr), duration);
            io.unobserve(e.target);
          }
        });
      }, { threshold: 0.35 });
      els.forEach((el) => io.observe(el));
    }

    observeAndAnimate('[data-count]',  'data-count',  2000);
    observeAndAnimate('[data-target]', 'data-target', 2000);
  })();


  /* 
     TURNOUT BARS 
      */
  (function initTurnout() {
    const fills = document.querySelectorAll('.t-fill');
    const block = document.querySelector('.turnout-block');
    if (!fills.length || !block) return;

    let animated = false;
    function animate() {
      if (animated) return;
      animated = true;
      fills.forEach((fill) => {
        const pct = fill.style.getPropertyValue('--pct') || '0%';
        fill.style.setProperty('--pct', '0%');
        setTimeout(() => fill.style.setProperty('--pct', pct), 80);
      });
    }

    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) animate(); });
      }, { threshold: 0.3 }).observe(block);
    } else {
      animate();
    }
  })();


  /* 
     FAQ ACCORDION
     */
  (function initFAQ() {
    document.querySelectorAll('.faq-question').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item   = btn.closest('.faq-item');
        const answer = item.querySelector('.faq-answer');
        const isOpen = btn.getAttribute('aria-expanded') === 'true';

        
        document.querySelectorAll('.faq-question[aria-expanded="true"]').forEach((other) => {
          if (other === btn) return;
          other.setAttribute('aria-expanded', 'false');
          other.closest('.faq-item').querySelector('.faq-answer').classList.remove('open');
        });

        btn.setAttribute('aria-expanded', String(!isOpen));
        answer.classList.toggle('open', !isOpen);
      });
    });
  })();


  /* 
      SMOOTH SCROLL 
     */
  (function initSmoothScroll() {
    const OFFSET = 80; 
    document.querySelectorAll('a[href^="#"]').forEach((a) => {
      a.addEventListener('click', (e) => {
        const href = a.getAttribute('href');
        if (!href || href === '#') return;
        const target = document.querySelector(href);
        if (!target) return;
        e.preventDefault();
        const top = target.getBoundingClientRect().top + window.scrollY - OFFSET;
        window.scrollTo({ top, behavior: 'smooth' });
      });
    });
  })();


  /* 
      STATS STRIP 
      */
  (function initParallax() {
    const strip = document.querySelector('.stats-strip');
    const bg    = document.querySelector('.stats-strip-bg');
    if (!strip || !bg) return;

    function onScroll() {
      const rect    = strip.getBoundingClientRect();
      const viewH   = window.innerHeight;
      if (rect.bottom < 0 || rect.top > viewH) return;
      const progress = (viewH - rect.top) / (viewH + rect.height);
      const offset   = (progress - 0.5) * 30;
      bg.style.transform = `scale(1.06) translateY(${offset}px)`;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  })();


  /* 
      STAGGER entrance for feature / position / tech cards
     */
  (function initCardStagger() {
    const cards = document.querySelectorAll(
      '.feature-card, .position-card, .tech-category, .visual-card',
    );
    if (!cards.length || !('IntersectionObserver' in window)) return;

    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.style.animationPlayState = 'running';
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    cards.forEach((card) => {
      card.style.animationPlayState = 'paused';
      io.observe(card);
    });
  })();

})();