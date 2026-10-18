// Renders the weekly quiz: each .duo-quiz div carries its questions in data-quiz.
document$.subscribe(function () {
  document.querySelectorAll(".duo-quiz[data-quiz]").forEach(function (root) {
    var quiz;
    try {
      quiz = JSON.parse(root.dataset.quiz);
    } catch (e) {
      root.textContent = "This quiz could not be loaded.";
      return;
    }
    buildQuiz(root, quiz);
  });
});

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function buildQuiz(root, quiz) {
  var LETTERS = "ABCDEF";
  var total = quiz.sections.reduce(function (n, s) { return n + s.questions.length; }, 0);
  var answered = 0;
  var correct = 0;
  var cards = [];

  root.textContent = "";

  var status = el("div", "duo-quiz__status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  var progress = el("div", "duo-quiz__progress");
  var bar = el("div", "duo-quiz__bar");
  progress.appendChild(bar);
  var statusText = el("span");
  status.appendChild(statusText);
  status.appendChild(progress);
  root.appendChild(status);

  var summary = el("div", "duo-quiz__summary");
  summary.hidden = true;

  function updateStatus() {
    statusText.textContent = answered + " / " + total + " answered · " + correct + " correct";
    bar.style.width = (total ? (answered / total) * 100 : 0) + "%";
    if (answered === total && total > 0) showSummary();
  }

  function showSummary() {
    var pct = Math.round((correct / total) * 100);
    summary.textContent = "";
    summary.appendChild(el("strong", null, "You scored " + correct + " / " + total + " (" + pct + "%)"));
    var msg = pct >= 90 ? "Excellent — the week's material is solid."
      : pct >= 70 ? "Good work. Review the explanations for the ones you missed."
      : "Worth another pass through the weekly review before trying again.";
    summary.appendChild(el("p", null, msg));
    var retry = el("button", "duo-quiz__retry", "Try again");
    retry.type = "button";
    retry.addEventListener("click", reset);
    summary.appendChild(retry);
    summary.hidden = false;
    summary.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function reset() {
    answered = 0;
    correct = 0;
    cards.forEach(function (c) { c.reset(); });
    summary.hidden = true;
    updateStatus();
    root.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  quiz.sections.forEach(function (section) {
    root.appendChild(el("h2", "duo-quiz__section", section.title));

    section.questions.forEach(function (q, qi) {
      var card = el("div", "duo-quiz__q");
      var meta = el("div", "duo-quiz__meta", (qi + 1) + " · " + (q.type === "vocab" ? "Vocabulary" : "Concept"));
      var text = el("p", "duo-quiz__text", q.question);
      text.dir = "auto";
      var list = el("div", "duo-quiz__options");
      list.setAttribute("role", "group");
      var feedback = el("p", "duo-quiz__explain");
      feedback.hidden = true;
      feedback.dir = "auto";

      var buttons = q.options.map(function (opt, oi) {
        var btn = el("button", "duo-quiz__option");
        btn.type = "button";
        btn.appendChild(el("span", "duo-quiz__letter", LETTERS[oi]));
        var label = el("span", "duo-quiz__label", opt);
        label.dir = "auto";
        btn.appendChild(label);
        btn.addEventListener("click", function () { choose(oi); });
        list.appendChild(btn);
        return btn;
      });

      var done = false;
      function choose(oi) {
        if (done) return;
        done = true;
        answered += 1;
        var right = oi === q.answer;
        if (right) correct += 1;
        buttons.forEach(function (b, i) {
          b.disabled = true;
          if (i === q.answer) b.classList.add("is-correct");
          else if (i === oi) b.classList.add("is-wrong");
        });
        feedback.textContent = (right ? "Correct. " : "Not quite. ") + (q.explanation || "");
        feedback.classList.toggle("is-right", right);
        feedback.hidden = false;
        updateStatus();
      }

      cards.push({
        reset: function () {
          done = false;
          buttons.forEach(function (b) {
            b.disabled = false;
            b.classList.remove("is-correct", "is-wrong");
          });
          feedback.hidden = true;
        },
      });

      card.appendChild(meta);
      card.appendChild(text);
      card.appendChild(list);
      card.appendChild(feedback);
      root.appendChild(card);
    });
  });

  root.appendChild(summary);
  updateStatus();
}
