# Ctrl-R fzf-style fuzzy/regex history search, backed by hist_search.py.
#
# Source this file from .zshrc, e.g.:
#   source /path/to/utils/hist_search/zsh_hist_search_widget.zsh
#
# Usage inside the picker:
#   type to fuzzy filter, Tab to switch to regex mode, Up/Down (or
#   Ctrl-P/Ctrl-N) to move one match, PageUp/PageDown to jump a full
#   page of matches, Enter to select, Esc/Ctrl-C to cancel.
#   Editing the search text: Left/Right (or Ctrl-B/Ctrl-F) to move the
#   cursor, Home/Ctrl-A and End/Ctrl-E to jump to the start/end,
#   Backspace/Delete to remove a character, Ctrl-K to kill to end of
#   line, Ctrl-U to kill to start of line.
# The chosen command is placed on the command line for editing; it is
# not run until you press Enter again.
#
# Whatever you'd already typed before pressing Ctrl-R (the left buffer)
# is passed through as the initial search query.
#
# Appearance (layout/colors/indicators) is controlled by hist_search.py's
# theme settings: ~/.hist_searchrc dotfile, or env vars, e.g.:
#   export HIST_SEARCH_THEME=fzf

_hist_search_dir="${${(%):-%x}:A:h}"

hist-search-widget() {
  local selected
  selected=$(HISTFILE="${HISTFILE:-$HOME/.zsh_history}" "$_hist_search_dir/hist_search.py" "$LBUFFER")
  if [[ -n "$selected" ]]; then
    BUFFER="$selected"
    CURSOR=${#BUFFER}
  fi
  zle reset-prompt
}
zle -N hist-search-widget
bindkey '^R' hist-search-widget
