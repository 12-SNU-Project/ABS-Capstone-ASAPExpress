export function GetNextStoryIndex(currentIndex, storyCount) {
  return storyCount > 0 ? (currentIndex + 1) % storyCount : 0;
}
