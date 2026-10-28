(function () {
  var bio = document.getElementById("id_bio"), count = document.querySelector("[data-count-for=id_bio]");
  function upd() { count.textContent = bio.value.length + " / 300"; }
  bio.addEventListener("input", upd); upd();
  var file = document.getElementById("id_avatar"), prev = document.getElementById("avatar-preview");
  file.addEventListener("change", function () {
    var f = file.files[0]; if (!f) return;
    var img = new Image(); img.alt = ""; img.src = URL.createObjectURL(f);
    prev.replaceChildren(img);
  });
})();
