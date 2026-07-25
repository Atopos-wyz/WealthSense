(() => {
  const header = document.getElementById("siteHeader");
  if (!header) return;
  const onScroll = () => {
    header.classList.toggle("scrolled", window.scrollY > 24);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
})();
