'use strict';
const navButton = document.querySelector('#nav-toggle');
const sidebar = document.querySelector('#site-sidebar');
function setNavigation(open) {
  sidebar.classList.toggle('is-open', open);
  navButton.setAttribute('aria-expanded', String(open));
  navButton.textContent = open ? '閉じる' : 'メニュー';
}
navButton.addEventListener('click', () => setNavigation(navButton.getAttribute('aria-expanded') !== 'true'));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && navButton.getAttribute('aria-expanded') === 'true') {
    setNavigation(false);
    navButton.focus();
  }
});
sidebar.querySelectorAll('nav a').forEach(link => link.addEventListener('click', () => setNavigation(false)));
window.matchMedia('(min-width: 801px)').addEventListener('change', () => setNavigation(false));
