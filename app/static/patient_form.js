(function () {
  "use strict";
  var dob = document.getElementById("dob");
  var ageField = document.getElementById("age-field");
  var guardianSection = document.getElementById("guardian-section");
  var guardianMobile = document.querySelector('[name="guardian_mobile"]');

  function computeAge() {
    if (!dob.value) {
      return;
    }
    var born = new Date(dob.value);
    var today = new Date();
    var age = today.getFullYear() - born.getFullYear();
    var m = today.getMonth() - born.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < born.getDate())) {
      age--;
    }
    ageField.value = age;
    toggleGuardianSection(age);
  }

  function toggleGuardianSection(age) {
    var isMinor = age !== null && age !== undefined && age < 18;
    guardianSection.hidden = !isMinor;
    if (guardianMobile) {
      guardianMobile.required = isMinor;
    }
  }

  dob.addEventListener("input", computeAge);
  ageField.addEventListener("input", function () {
    var age = parseInt(ageField.value, 10);
    toggleGuardianSection(isNaN(age) ? null : age);
  });

  if (dob.value) {
    computeAge();
  } else if (ageField.value) {
    toggleGuardianSection(parseInt(ageField.value, 10));
  }
})();
