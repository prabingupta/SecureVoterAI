/**
 * SecureVoter AI — voter_dashboard/main.js
 * Shared JavaScript for all voter dashboard pages.
 * Covers: scroll animations, intersection observer reveals,
 *         form helpers, accessibility, ripple effects.
 */

'use strict';

// ── DOMContentLoaded ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  initScrollReveal();
  initRippleButtons();
  initActiveNavHighlight();

});


// ================================================================
// SCROLL REVEAL — fade-up elements on entering viewport
// ================================================================
function initScrollReveal() {
  const elements = document.querySelectorAll(
    '.election-card, .stat-card, .profile-section-card, .glass-card, .ai-verify-item'
  );

  if (!elements.length || !('IntersectionObserver' in window)) return;

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, index) => {
        if (entry.isIntersecting) {
          // Stagger delay based on sibling index
          const siblings = Array.from(entry.target.parentElement?.children || []);
          const i = siblings.indexOf(entry.target);
          entry.target.style.animationDelay = `${i * 0.07}s`;
          entry.target.classList.add('reveal-visible');
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
  );

  elements.forEach((el) => {
    el.classList.add('reveal-hidden');
    observer.observe(el);
  });

  // Inject reveal styles if not already present
  if (!document.getElementById('revealStyles')) {
    const style = document.createElement('style');
    style.id = 'revealStyles';
    style.textContent = `
      .reveal-hidden {
        opacity: 0;
        transform: translateY(18px);
        transition: opacity 0.45s ease, transform 0.45s ease;
      }
      .reveal-visible {
        opacity: 1 !important;
        transform: translateY(0) !important;
      }
    `;
    document.head.appendChild(style);
  }
}


// ================================================================
// RIPPLE EFFECT on .btn-vote and .btn-solid
// ================================================================
function initRippleButtons() {
  const buttons = document.querySelectorAll('.btn-vote, .btn-solid, .btn-submit-vote');

  buttons.forEach((btn) => {
    btn.addEventListener('click', function (e) {
      const rect = btn.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const ripple = document.createElement('span');
      ripple.style.cssText = `
        position: absolute;
        left: ${x}px;
        top: ${y}px;
        width: 0; height: 0;
        transform: translate(-50%, -50%);
        background: rgba(255,255,255,0.22);
        border-radius: 50%;
        pointer-events: none;
        animation: rippleExpand 0.6s ease-out forwards;
      `;

      btn.style.position = 'relative';
      btn.style.overflow = 'hidden';
      btn.appendChild(ripple);

      ripple.addEventListener('animationend', () => ripple.remove());
    });
  });

  // Inject ripple keyframes once
  if (!document.getElementById('rippleStyles')) {
    const style = document.createElement('style');
    style.id = 'rippleStyles';
    style.textContent = `
      @keyframes rippleExpand {
        to {
          width: 300px;
          height: 300px;
          opacity: 0;
        }
      }
    `;
    document.head.appendChild(style);
  }
}


// ================================================================
// ACTIVE NAV HIGHLIGHT — mark current page link
// ================================================================
function initActiveNavHighlight() {
  const currentPath = window.location.pathname;
  const navLinks    = document.querySelectorAll('.nav-links a');

  navLinks.forEach((link) => {
    // Already handled by Django template tag, but reinforce in JS
    if (link.href && link.href.includes(currentPath) && currentPath !== '/') {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    }
  });
}


// ================================================================
// UTILITY: Format datetime string to relative time
// ================================================================
function timeAgo(dateString) {
  const date  = new Date(dateString);
  const now   = new Date();
  const diff  = Math.floor((now - date) / 1000);

  if (diff < 60)     return 'just now';
  if (diff < 3600)   return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)  return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ================================================================
// UTILITY: Debounce
// ================================================================
function debounce(fn, delay = 150) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}