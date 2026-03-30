const statusNode = document.getElementById("status");
const button = document.getElementById("downloadButton");
const postUrlNode = document.getElementById("postUrl");
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

button.addEventListener("click", async () => {
  button.disabled = true;
  setStatus("Collecting images...");

  try {
    const postUrl = normalizePostUrl(postUrlNode.value);
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
      filePrefix
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Could not download images.");
    }

    setStatus(`Queued ${response.count} image(s) for download.\nPrefix: ${filePrefix}`);
  } catch (error) {
    setStatus(error.message || String(error));
  } finally {
    button.disabled = false;
  }
});
