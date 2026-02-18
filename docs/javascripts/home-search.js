// Wire the custom home-page search input to MkDocs Material's built-in search
document.addEventListener("DOMContentLoaded", function () {
  var homeInput = document.querySelector("[data-md-component='home-search-input']");
  if (!homeInput) return;

  homeInput.addEventListener("focus", function () {
    // Trigger the built-in search dialog by simulating the keyboard shortcut
    var searchInput = document.querySelector(".md-search__input");
    if (searchInput) {
      document.querySelector("[data-md-toggle='search']").checked = true;
      searchInput.focus();
    }
  });
});
