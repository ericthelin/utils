# Ctrl-R fzf-style fuzzy/regex history search, backed by hist_search.py.
#
# Source this file from .zshrc, e.g.:
#   source /path/to/utils/hist_search/zsh_hist_search_widget.zsh
#
# Usage inside the picker:
#   type to fuzzy filter, Tab to switch to regex mode, Up/Down (or
#   Ctrl-P/Ctrl-N) to move, Enter to select, Esc/Ctrl-C to cancel.
# The chosen command is placed on the command line for editing; it is
# not run until you press Enter again.

_hist_search_dir="${${(%):-%x}:A:h}"

hist-search-widget() {
  local selected
  selected=$(HISTFILE="${HISTFILE:-$HOME/.zsh_history}" "$_hist_search_dir/hist_search.py")
  if [[ -n "$selected" ]]; then
    BUFFER="$selected"
    CURSOR=${#BUFFER}
  fi
  zle reset-prompt
}
zle -N hist-search-widget
bindkey '^R' hist-search-widget
