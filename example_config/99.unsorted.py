from pkgmgr.registry import MANAGERS, Package


shsh = MANAGERS["shsh"]
(
    shsh
    << "soraxas/yadm"
    << "soraxas/git-utils"
    << "soraxas/git-utilins"
    << "soraxas/open-rev-ports"
    << "so-fancy/diff-so-fancy"
    << "elasticdog/transcrypt"
    << Package("tj/git-extras", extra="-h pre='PREFIX=myroot make' -v ROOT=myroot")
)


fisher = MANAGERS["fisher"]
(
    fisher
    << "soraxas/fisher"  # modified fisher that supports comments and omf
    << "jorgebucaran/replay.fish"  # similar to bass, but with pure fish
    << "patrickf1/fzf.fish"
    << "wfxr/forgit"
    << "jorgebucaran/autopair.fish"
    # matchai/spacefish # for shell without starship
    #
    # soraxas/fish-cool-right-prompt
    # IlanCosman/tide
    << "soraxas/rgg.fish"  # rg with number selection
    << "soraxas/fish-things"
    << "jethrokuan/z"
    << "otms61/fish-pet"
    << "oakninja/makemefish"
    << "otms61/fish-pet"
    << "soraxas/breeze.fish"
    << "acomagu/fish-async-prompt"
)
