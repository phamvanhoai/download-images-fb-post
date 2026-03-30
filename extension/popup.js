const statusNode = document.getElementById("status");
const button = document.getElementById("downloadButton");
const postUrlNode = document.getElementById("postUrl");
const saveFolderNode = document.getElementById("saveFolder");
const filePrefixNode = document.getElementById("filePrefix");

function setStatus(message) {
  statusNode.textContent = message;
}

function normalizePostUrl(value) {
  return (value || "").trim();
}

function normalizeFilePrefix(value) {
  return (value || "").trim() || "facebook_post";
}

function normalizeSaveFolder(value) {
  return (value || "").trim() || "facebook-post-images";
}

button.addEventListener("click", async () => {
  button.disabled = true;
  setStatus("Collecting images...");

  try {
    const postUrl = normalizePostUrl(postUrlNode.value);
    const saveFolder = normalizeSaveFolder(saveFolderNode.value);
    const filePrefix = normalizeFilePrefix(filePrefixNode.value);

    if (!postUrl) {
      throw new Error("Please paste a Facebook post link first.");
    }
    if (!postUrl.includes("facebook.com")) {
      throw new Error("This does not look like a Facebook post link.");
    }

    const response = await chrome.runtime.sendMessage({
      type: "download-post-images-by-url",
      postUrl,
      saveFolder,
      filePrefix
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Could not download images.");
    }

    setStatus(`Queued ${response.count} image(s) for download.\nFolder: ${saveFolder}\nPrefix: ${filePrefix}`);
  } catch (error) {
    setStatus(error.message || String(error));
  } finally {
    button.disabled = false;
  }
});
