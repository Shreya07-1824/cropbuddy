document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("flashModal");
  const message = document.getElementById("flashMessage");
  const closeBtn = document.getElementById("closeModal");

  // Message is passed from Flask flash -> template
  if (modal && message && message.textContent.trim() !== "") {
    modal.style.display = "flex";
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      modal.style.display = "none";
    });
  }

  // Optional: close when clicking outside the box
  window.addEventListener("click", e => {
    if (e.target === modal) modal.style.display = "none";
  });
});