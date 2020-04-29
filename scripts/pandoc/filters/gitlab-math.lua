function Math(el)
    if el.mathtype == "InlineMath" then
        return {pandoc.RawInline('html','$`' .. el.text .. '`$')}
	else
		return {pandoc.RawInline('html','```math\n' .. el.text .. '\n```')}
    end
end
