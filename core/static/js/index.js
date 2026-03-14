
(function () {
  'use strict';

 
  const SliderModule = (function () {
    const slides   = document.querySelectorAll('.hero-slider .slide');
    const dotsWrap = document.getElementById('sliderDots');
    const prevBtn  = document.getElementById('prevSlide');
    const nextBtn  = document.getElementById('nextSlide');

    if (!slides.length) return;

    let current = 0;
    let timer   = null;
    const DELAY = 6000;

    /* Build dot indicators */
    const dots = [];
    slides.forEach((_, i) => {
      const dot = document.createElement('button');
      dot.classList.add('dot');
      dot.setAttribute('aria-label', `Go to slide ${i + 1}`);
      if (i === 0) dot.classList.add('active');
      dot.addEventListener('click', () => goTo(i));
      dotsWrap && dotsWrap.appendChild(dot);
      dots.push(dot);
    });

    function goTo(index) {
      slides[current].classList.remove('active');
      dots[current]  && dots[current].classList.remove('active');
      current = (index + slides.length) % slides.length;
      slides[current].classList.add('active');
      dots[current]  && dots[current].classList.add('active');
      resetTimer();
    }

    function next() { goTo(current + 1); }
    function prev() { goTo(current - 1); }

    function resetTimer() {
      clearInterval(timer);
      timer = setInterval(next, DELAY);
    }

    prevBtn && prevBtn.addEventListener('click', prev);
    nextBtn && nextBtn.addEventListener('click', next);

    /* Keyboard navigation */
    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft')  prev();
      if (e.key === 'ArrowRight') next();
    });

    /* Touch / swipe */
    let touchStartX  = 0;
    const heroSection = document.getElementById('hero');
    if (heroSection) {
      heroSection.addEventListener('touchstart', (e) => {
        touchStartX = e.changedTouches[0].screenX;
      }, { passive: true });

      heroSection.addEventListener('touchend', (e) => {
        const diff = touchStartX - e.changedTouches[0].screenX;
        if (Math.abs(diff) > 50) diff > 0 ? next() : prev();
      }, { passive: true });

      /* Pause on hover */
      heroSection.addEventListener('mouseenter', () => clearInterval(timer));
      heroSection.addEventListener('mouseleave', () => resetTimer());
    }

    resetTimer();
  })();



  const CounterModule = (function () {

    /* ── Shared easing & animation ── */
    function easeOutQuart(t) {
      return 1 - Math.pow(1 - t, 4);
    }

    function animateCounter(el, target, duration) {
      const start = performance.now();

      function step(now) {
        const elapsed  = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const value    = Math.floor(easeOutQuart(progress) * target);
        el.textContent = value.toLocaleString();
        if (progress < 1) {
          requestAnimationFrame(step);
        } else {
          el.textContent = target.toLocaleString();
        }
      }

      requestAnimationFrame(step);
    }

    /* ── A. Hero stats: [data-count] ── */
    (function initHeroCounters() {
      const counters = document.querySelectorAll('[data-count]');
      if (!counters.length) return;

      let triggered = false;

      function startAll() {
        if (triggered) return;
        triggered = true;
        counters.forEach((el) => {
          const target   = parseInt(el.getAttribute('data-count'), 10);
          const duration = 2000 + Math.random() * 400;
          animateCounter(el, target, duration);
        });
      }

      const statsSection = document.querySelector('.hero-stats');
      if (!statsSection) { startAll(); return; }

      if ('IntersectionObserver' in window) {
        const io = new IntersectionObserver((entries) => {
          entries.forEach((entry) => { if (entry.isIntersecting) startAll(); });
        }, { threshold: 0.4 });
        io.observe(statsSection);
      } else {
        startAll();
      }
    })();

    /* ── B. Stats strip: [data-target] ── */
    (function initStripCounters() {
      const counters = document.querySelectorAll('.stat-count[data-target]');
      if (!counters.length) return;

      if ('IntersectionObserver' in window) {
        const io = new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const el     = entry.target;
              const target = parseInt(el.dataset.target, 10);
              animateCounter(el, target, 2000);
              io.unobserve(el);
            }
          });
        }, { threshold: 0.35 });

        counters.forEach((el) => io.observe(el));
      } else {
        /* Fallback: animate immediately */
        counters.forEach((el) => {
          animateCounter(el, parseInt(el.dataset.target, 10), 2000);
        });
      }
    })();

  })();


  /* 
     3. ELECTION COUNTDOWN TIMER
  */
  const CountdownModule = (function () {
    const daysEl  = document.getElementById('cd-days');
    const hoursEl = document.getElementById('cd-hours');
    const minsEl  = document.getElementById('cd-mins');
    const secsEl  = document.getElementById('cd-secs');

    if (!daysEl) return;

    /* ── Set your election close date/time here ── */
    const TARGET_DATE = new Date('2026-06-15T23:59:59');

    function pad(n) {
      return String(n).padStart(2, '0');
    }

    function tick() {
      const now  = new Date();
      const diff = TARGET_DATE - now;

      if (diff <= 0) {
        daysEl.textContent  = '00';
        hoursEl.textContent = '00';
        minsEl.textContent  = '00';
        secsEl.textContent  = '00';

        const statusPill = document.querySelector('.election-status-pill');
        if (statusPill) {
          statusPill.innerHTML =
            '<span class="pulse-dot" style="background:#ff4d6d;box-shadow:0 0 6px #ff4d6d"></span> Election Closed';
          statusPill.style.background  = 'rgba(255,77,109,0.12)';
          statusPill.style.borderColor = 'rgba(255,77,109,0.28)';
          statusPill.style.color       = '#ff4d6d';
        }
        return;
      }

      const totalSecs = Math.floor(diff / 1000);
      const days      = Math.floor(totalSecs / 86400);
      const hours     = Math.floor((totalSecs % 86400) / 3600);
      const mins      = Math.floor((totalSecs % 3600)  / 60);
      const secs      = totalSecs % 60;

      daysEl.textContent  = pad(days);
      hoursEl.textContent = pad(hours);
      minsEl.textContent  = pad(mins);
      secsEl.textContent  = pad(secs);

      /* Tick-pulse on the seconds digit */
      secsEl.classList.remove('tick-pulse');
      void secsEl.offsetWidth;
      secsEl.classList.add('tick-pulse');
    }

    tick();
    setInterval(tick, 1000);
  })();


  /* 
     4. FAQ ACCORDION
  */
  const FAQModule = (function () {
    const items = document.querySelectorAll('.faq-item');
    if (!items.length) return;

    items.forEach((item) => {
      const btn    = item.querySelector('.faq-question');
      const answer = item.querySelector('.faq-answer');
      if (!btn || !answer) return;

      btn.addEventListener('click', () => {
        const isOpen = btn.getAttribute('aria-expanded') === 'true';

        /* Collapse all other items */
        items.forEach((other) => {
          if (other === item) return;
          const otherBtn    = other.querySelector('.faq-question');
          const otherAnswer = other.querySelector('.faq-answer');
          otherBtn    && otherBtn.setAttribute('aria-expanded', 'false');
          otherAnswer && otherAnswer.classList.remove('open');
        });

        /* Toggle current */
        btn.setAttribute('aria-expanded', String(!isOpen));
        answer.classList.toggle('open', !isOpen);
      });
    });
  })();


  /* 
     5. TURNOUT BARS — Animate on scroll into view
 */
  const TurnoutModule = (function () {
    const fills = document.querySelectorAll('.t-fill');
    if (!fills.length) return;

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

    const block = document.querySelector('.turnout-block');
    if (!block) return;

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) animate(); });
      }, { threshold: 0.3 });
      io.observe(block);
    } else {
      animate();
    }
  })();


  /*
     6. NAVBAR SCROLL SHADOW
 */
  const NavbarModule = (function () {
    const navbar = document.getElementById('navbar');
    if (!navbar) return;

    function onScroll() {
      navbar.classList.toggle('navbar-scrolled', window.scrollY > 40);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  })();


  /* ──────────────────────────────────────────────────────────
     7. SMOOTH SCROLL — in-page anchor links
  ────────────────────────────────────────────────────────── */
  const SmoothScrollModule = (function () {
    const NAVBAR_H = 68;

    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
      anchor.addEventListener('click', (e) => {
        const href = anchor.getAttribute('href');
        if (!href || href === '#') return;

        const target = document.querySelector(href);
        if (!target) return;

        e.preventDefault();
        const top = target.getBoundingClientRect().top + window.scrollY - NAVBAR_H - 16;
        window.scrollTo({ top, behavior: 'smooth' });
      });
    });
  })();


  /*
     8. FEATURE CARDS — Stagger entrance animation on scroll
  */
  const FeatureStaggerModule = (function () {
    const cards = document.querySelectorAll('.feature-card, .position-card, .tech-category');
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


  /*
     9. TIMELINE ITEMS — Fade-up on scroll
 */
  const TimelineModule = (function () {
    const items = document.querySelectorAll('.timeline-item');
    if (!items.length || !('IntersectionObserver' in window)) return;

    items.forEach((item) => {
      item.style.opacity    = '0';
      item.style.transform  = 'translateY(18px)';
      item.style.transition = 'opacity 0.55s ease, transform 0.55s ease';
    });

    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.style.opacity   = '1';
          entry.target.style.transform = 'translateY(0)';
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.18 });

    items.forEach((item) => io.observe(item));
  })();


  /*
     10. MOBILE NAV TOGGLE
  */
  const MobileNavModule = (function () {
    const toggle = document.querySelector('.nav-toggle');
    const nav    = document.querySelector('.navigation');
    if (!toggle || !nav) return;

    function openNav() {
      nav.classList.add('nav-open');
      toggle.classList.add('open');
      toggle.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
    }

    function closeNav() {
      nav.classList.remove('nav-open');
      toggle.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }

    function isOpen() {
      return nav.classList.contains('nav-open');
    }

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      isOpen() ? closeNav() : openNav();
    });

    nav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => closeNav());
    });

    document.addEventListener('click', (e) => {
      if (!isOpen()) return;
      if (!nav.contains(e.target) && !toggle.contains(e.target)) closeNav();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen()) closeNav();
    });

    const mediaQuery = window.matchMedia('(min-width: 769px)');
    mediaQuery.addEventListener('change', (e) => {
      if (e.matches && isOpen()) closeNav();
    });
  })();


  /* 
     11. ELECTION BANNER
  */
  const BannerModule = (function () {
    const banner = document.getElementById('electionBanner');
    if (!banner) return;

    if (sessionStorage.getItem('sv_banner_closed')) {
      banner.style.display = 'none';
      return;
    }

    const closeBtn = banner.querySelector('.banner-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        banner.style.transition = 'max-height 0.4s ease, opacity 0.4s ease, padding 0.4s ease';
        banner.style.maxHeight  = '0';
        banner.style.opacity    = '0';
        banner.style.padding    = '0';
        banner.style.overflow   = 'hidden';
        sessionStorage.setItem('sv_banner_closed', '1');
      });
    }
  })();


  /* 
     12. STATS STRIP — Parallax on scroll
   */
  const StatsParallaxModule = (function () {
    const strip = document.querySelector('.stats-strip');
    const bg    = document.querySelector('.stats-strip-bg');
    if (!strip || !bg) return;

    function onScroll() {
      const rect   = strip.getBoundingClientRect();
      const viewH  = window.innerHeight;

      /* Only run when the strip is visible */
      if (rect.bottom < 0 || rect.top > viewH) return;

      /* Map scroll position to a small vertical offset (-15px → +15px) */
      const progress = (viewH - rect.top) / (viewH + rect.height);
      const offset   = (progress - 0.5) * 30; /* 30px total travel */
      bg.style.transform = `scale(1.06) translateY(${offset}px)`;
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  })();


  /*
     13. AOS INIT (guard against double-init from base.html)
 */
  if (typeof AOS !== 'undefined' && !AOS._initialized) {
    AOS.init({
      duration: 750,
      once:     true,
      offset:   55,
      easing:   'ease-out-cubic',
    });
    AOS._initialized = true;
  }

})();