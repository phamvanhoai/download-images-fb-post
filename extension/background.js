async function sendToTab(tabId, func, args = []) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func,
    args
  });
  return result?.result;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function sanitizeName(value) {
  return value.replace(/[<>:"|?*]+/g, "_").trim() || "download";
}

function normalizeFilePrefix(value) {
  return sanitizeName((value || "").trim() || "facebook_post").replace(/[\\/]+/g, "_");
}

function normalizeSaveFolder(value) {
  const raw = (value || "").trim() || "facebook-post-images";
  return raw
    .split(/[\\/]+/)
    .map((segment) => sanitizeName(segment))
    .filter(Boolean)
    .join("/") || "facebook-post-images";
}

function getImageFingerprint(imageUrl) {
  try {
    const parsed = new URL(imageUrl);
    const fileName = parsed.pathname.split("/").pop() || parsed.pathname;
    return `${parsed.hostname}${parsed.pathname}|${fileName}`;
  } catch {
    return imageUrl;
  }
}

function isCandidateFacebookImage(imageUrl, width, height, alt = "") {
  if (!imageUrl) {
    return false;
  }

  if (!imageUrl.includes("fbcdn.net") && !imageUrl.includes("scontent")) {
    return false;
  }

  const normalizedAlt = (alt || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");

  if (normalizedAlt.includes("profile picture") || normalizedAlt.includes("avatar")) {
    return false;
  }

  const imageWidth = width || 0;
  const imageHeight = height || 0;
  const area = imageWidth * imageHeight;

  return imageWidth >= 120 && imageHeight >= 120 && area >= 20000;
}

function buildFilename(index, imageUrl, filePrefix) {
  const prefix = normalizeFilePrefix(filePrefix);
  try {
    const parsed = new URL(imageUrl);
    const pathName = parsed.pathname.split("/").pop() || `image_${index}.jpg`;
    const extension = pathName.includes(".") ? pathName.slice(pathName.lastIndexOf(".")) : ".jpg";
    return sanitizeName(`${prefix}_${String(index).padStart(3, "0")}${extension}`);
  } catch {
    return `${prefix}_${String(index).padStart(3, "0")}.jpg`;
  }
}

async function waitForTabReady(tabId, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") {
      await sleep(1200);
      return;
    }
    await sleep(500);
  }
  throw new Error("Timed out while opening the Facebook post.");
}

async function collectImagesViaViewer(tabId) {
  return sendToTab(
    tabId,
    async () => {
      const normalize = (url) => {
        if (!url) {
          return "";
        }
        if (url.startsWith("//")) {
          return `https:${url}`;
        }
        return url;
      };

      const normalizeLabel = (value) => {
        return (value || "")
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "");
      };

      const getImageFingerprintLocal = (imageUrl) => {
        try {
          const parsed = new URL(imageUrl);
          const fileName = parsed.pathname.split("/").pop() || parsed.pathname;
          return `${parsed.hostname}${parsed.pathname}|${fileName}`;
        } catch {
          return imageUrl;
        }
      };

      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

      const isViewerCandidate = (src, width, height, alt) => {
        if (!src) {
          return false;
        }
        if (!src.includes("fbcdn.net") && !src.includes("scontent")) {
          return false;
        }
        const altText = normalizeLabel(alt);
        if (altText.includes("profile picture") || altText.includes("avatar")) {
          return false;
        }
        return width >= 120 && height >= 120 && width * height >= 20000;
      };

      const getViewerState = () => {
        const candidates = [];
        for (const img of document.querySelectorAll("img")) {
          const src = normalize(
            img.currentSrc ||
              img.src ||
              img.getAttribute("src") ||
              img.getAttribute("data-src") ||
              ""
          );
          const width = img.naturalWidth || 0;
          const height = img.naturalHeight || 0;
          const alt = img.alt || "";
          const area = width * height;

          if (!isViewerCandidate(src, width, height, alt)) {
            continue;
          }

          candidates.push({ src, area });
        }

        candidates.sort((a, b) => b.area - a.area);
        return {
          viewerUrl: location.href,
          imageUrl: candidates[0]?.src || null
        };
      };

      const openFirstImage = () => {
        const candidates = [];
        for (const anchor of document.querySelectorAll("a[href]")) {
          const href = anchor.href || "";
          if (!href.includes("facebook.com")) {
            continue;
          }
          if (!href.includes("/photo/") && !href.includes("fbid=")) {
            continue;
          }

          const rect = anchor.getBoundingClientRect();
          if (rect.width < 80 || rect.height < 80) {
            continue;
          }

          candidates.push({ anchor, area: rect.width * rect.height });
        }

        candidates.sort((a, b) => b.area - a.area);
        const target = candidates[0]?.anchor;
        if (!target) {
          return false;
        }

        target.click();
        return true;
      };

      const nextSelectors = [
        '[aria-label="Next photo"]',
        '[aria-label="View next photo"]',
        '[aria-label="See next photo"]',
        '[aria-label*="next photo" i]'
      ];

      const findNextButton = () => {
        for (const selector of nextSelectors) {
          const button = document.querySelector(selector);
          if (!button) {
            continue;
          }
          const rect = button.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) {
            continue;
          }
          return button;
        }

        const buttons = Array.from(document.querySelectorAll('[role="button"], div[tabindex="0"]'));
        const matching = buttons.filter((button) => {
          const label = normalizeLabel(
            button.getAttribute("aria-label") ||
            button.textContent ||
            ""
          );
          const rect = button.getBoundingClientRect();
          return (
            rect.width > 0 &&
            rect.height > 0 &&
            (label.includes("next photo") || label.includes("tiep theo"))
          );
        });
        return matching[0] || null;
      };

      if (!openFirstImage()) {
        return [];
      }

      await wait(1800);

      const imageUrls = [];
      const seenViewerUrls = new Set();
      const seenImageKeys = new Set();
      let repeatedImageRounds = 0;

      for (let step = 0; step < 120; step += 1) {
        const state = getViewerState();
        const viewerUrl = state.viewerUrl || "";
        const imageUrl = state.imageUrl;

        if (viewerUrl && seenViewerUrls.has(viewerUrl)) {
          break;
        }
        if (viewerUrl) {
          seenViewerUrls.add(viewerUrl);
        }

        if (imageUrl) {
          const imageKey = getImageFingerprintLocal(imageUrl);
          if (!seenImageKeys.has(imageKey)) {
            seenImageKeys.add(imageKey);
            imageUrls.push(imageUrl);
            repeatedImageRounds = 0;
          } else {
            repeatedImageRounds += 1;
          }
        } else {
          repeatedImageRounds += 1;
        }

        const nextButton = findNextButton();
        if (!nextButton) {
          break;
        }
        if (repeatedImageRounds >= 2) {
          break;
        }

        nextButton.click();
        await wait(1200);
      }

      return imageUrls;
    }
  );
}

async function collectImagesFromFallback(tabId, postUrl) {
  const photoLinks = await sendToTab(
    tabId,
    (currentPostUrl) => {
      const normalize = (url) => {
        if (!url) {
          return "";
        }
        if (url.startsWith("//")) {
          return `https:${url}`;
        }
        return url;
      };

      const links = [];
      const seen = new Set();
      const markers = ["/photo/", "fbid=", "/posts/", "/media/set/"];

      for (const anchor of document.querySelectorAll("a[href]")) {
        const href = normalize(anchor.href);
        if (!href) {
          continue;
        }

        const absolute = new URL(href, currentPostUrl).href;
        if (!absolute.includes("facebook.com")) {
          continue;
        }
        if (!markers.some((marker) => absolute.includes(marker))) {
          continue;
        }
        if (seen.has(absolute)) {
          continue;
        }

        seen.add(absolute);
        links.push(absolute);
      }

      return links;
    },
    [postUrl]
  );

  const imageUrls = [];
  const seenImageKeys = new Set();

  for (const link of photoLinks || []) {
    const photoTab = await chrome.tabs.create({ url: link, active: false });
    try {
      await waitForTabReady(photoTab.id, 20000);
      const imageUrl = await sendToTab(photoTab.id, () => {
        const normalize = (url) => {
          if (!url) {
            return "";
          }
          if (url.startsWith("//")) {
            return `https:${url}`;
          }
          return url;
        };

        const isCandidateFacebookImageLocal = (src, width, height) => {
          if (!src) {
            return false;
          }
          if (!src.includes("fbcdn.net") && !src.includes("scontent")) {
            return false;
          }
          return width >= 120 && height >= 120 && width * height >= 20000;
        };

        const candidates = [];
        for (const img of document.querySelectorAll("img")) {
          const src = normalize(
            img.currentSrc ||
              img.src ||
              img.getAttribute("src") ||
              img.getAttribute("data-src") ||
              ""
          );
          const width = img.naturalWidth || 0;
          const height = img.naturalHeight || 0;
          if (!isCandidateFacebookImageLocal(src, width, height)) {
            continue;
          }
          candidates.push({ src, area: width * height });
        }
        candidates.sort((a, b) => b.area - a.area);
        return candidates[0]?.src || null;
      });

      if (imageUrl) {
        const key = getImageFingerprint(imageUrl);
        if (!seenImageKeys.has(key)) {
          seenImageKeys.add(key);
          imageUrls.push(imageUrl);
        }
      }
    } finally {
      await chrome.tabs.remove(photoTab.id);
    }
  }

  if (imageUrls.length > 0) {
    return imageUrls;
  }

  const inlineImages = await sendToTab(tabId, () => {
    const normalize = (url) => {
      if (!url) {
        return "";
      }
      if (url.startsWith("//")) {
        return `https:${url}`;
      }
      return url;
    };

    const isCandidateFacebookImageLocal = (src, width, height, alt) => {
      if (!src) {
        return false;
      }
      if (!src.includes("fbcdn.net") && !src.includes("scontent")) {
        return false;
      }
      const normalizedAlt = (alt || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");
      if (normalizedAlt.includes("profile picture") || normalizedAlt.includes("avatar")) {
        return false;
      }
      return width >= 120 && height >= 120 && width * height >= 20000;
    };

    const images = [];
    const seen = new Set();

    for (const img of document.querySelectorAll("img")) {
      const src = normalize(
        img.currentSrc ||
          img.src ||
          img.getAttribute("src") ||
          img.getAttribute("data-src") ||
          ""
      );
      const width = img.naturalWidth || 0;
      const height = img.naturalHeight || 0;
      const alt = img.alt || "";

      if (!isCandidateFacebookImageLocal(src, width, height, alt)) {
        continue;
      }
      const key = src;
      if (seen.has(key)) {
        continue;
      }

      seen.add(key);
      images.push(src);
    }

    return images;
  });

  for (const imageUrl of inlineImages || []) {
    const key = getImageFingerprint(imageUrl);
    if (!seenImageKeys.has(key)) {
      seenImageKeys.add(key);
      imageUrls.push(imageUrl);
    }
  }

  return imageUrls;
}

async function collectImagesFromFacebookPost(tabId, postUrl) {
  const viewerImages = await collectImagesViaViewer(tabId);
  if (viewerImages.length > 0) {
    return viewerImages;
  }
  return collectImagesFromFallback(tabId, postUrl);
}

async function queueDownloads(imageUrls, filePrefix, saveFolder) {
  let count = 0;
  const queuedKeys = new Set();
  const normalizedFolder = normalizeSaveFolder(saveFolder);

  for (let index = 0; index < imageUrls.length; index += 1) {
    const imageUrl = imageUrls[index];
    const key = getImageFingerprint(imageUrl);
    if (queuedKeys.has(key)) {
      continue;
    }
    queuedKeys.add(key);

    await chrome.downloads.download({
      url: imageUrl,
      filename: `${normalizedFolder}/${buildFilename(count + 1, imageUrl, filePrefix)}`,
      saveAs: false
    });
    count += 1;
  }

  return count;
}

async function downloadPostImagesByUrl(postUrl, filePrefix, saveFolder) {
  const workerTab = await chrome.tabs.create({ url: postUrl, active: false });
  try {
    await waitForTabReady(workerTab.id);
    const imageUrls = await collectImagesFromFacebookPost(workerTab.id, postUrl);
    if (imageUrls.length === 0) {
      throw new Error("Could not find images in this post.");
    }
    const count = await queueDownloads(imageUrls, filePrefix, saveFolder);
    return { ok: true, count };
  } finally {
    await chrome.tabs.remove(workerTab.id);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "download-post-images-by-url") {
    (async () => {
      try {
        const response = await downloadPostImagesByUrl(message.postUrl, message.filePrefix, message.saveFolder);
        sendResponse(response);
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  if (message?.type === "download-current-post-images") {
    (async () => {
      try {
        const imageUrls = await collectImagesFromFacebookPost(message.tabId, message.postUrl);
        if (imageUrls.length === 0) {
          throw new Error("Could not find images in this post.");
        }

        const count = await queueDownloads(imageUrls, message.filePrefix, message.saveFolder);
        sendResponse({ ok: true, count });
      } catch (error) {
        sendResponse({ ok: false, error: error.message || String(error) });
      }
    })();
    return true;
  }

  return false;
});
